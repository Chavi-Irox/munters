# remotenames.py - extension to display remotenames
#
# Copyright 2017 Augie Fackler <raf@durin42.com>
# Copyright 2017 Sean Farley <sean@farley.io>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

""" showing remotebookmarks and remotebranches in UI (EXPERIMENTAL)

By default both remotebookmarks and remotebranches are turned on. Config knob to
control the individually are as follows.

Config options to tweak the default behaviour:

remotenames.bookmarks
  Boolean value to enable or disable showing of remotebookmarks (default: True)

remotenames.branches
  Boolean value to enable or disable showing of remotebranches (default: True)

remotenames.hoistedpeer
  Name of the peer whose remotebookmarks should be hoisted into the top-level
  namespace (default: 'default')
"""

from __future__ import absolute_import

from mercurial.i18n import _

from mercurial.node import (
    bin,
)
from mercurial import (
    bookmarks,
    extensions,
    logexchange,
    namespaces,
    pycompat,
    registrar,
    revsetlang,
    smartset,
    templateutil,
)

if pycompat.ispy3:
    import collections.abc
    mutablemapping = collections.abc.MutableMapping
else:
    import collections
    mutablemapping = collections.MutableMapping

# Note for extension authors: ONLY specify testedwith = 'ships-with-hg-core' for
# extensions which SHIP WITH MERCURIAL. Non-mainline extensions should
# be specifying the version(s) of Mercurial they are tested with, or
# leave the attribute unspecified.
testedwith = 'ships-with-hg-core'

configtable = {}
configitem = registrar.configitem(configtable)
templatekeyword = registrar.templatekeyword()
revsetpredicate = registrar.revsetpredicate()

configitem('remotenames', 'bookmarks',
    default=True,
)
configitem('remotenames', 'branches',
    default=True,
)
configitem('remotenames', 'hoistedpeer',
    default='default',
)

class lazyremotenamedict(mutablemapping):
    """
    Read-only dict-like Class to lazily resolve remotename entries

    We are doing that because remotenames startup was slow.
    We lazily read the remotenames file once to figure out the potential entries
    and store them in self.potentialentries. Then when asked to resolve an
    entry, if it is not in self.potentialentries, then it isn't there, if it
    is in self.potentialentries we resolve it and store the result in
    self.cache. We cannot be lazy is when asked all the entries (keys).
    """
    def __init__(self, kind, repo):
        self.cache = {}
        self.potentialentries = {}
        self._kind = kind # bookmarks or branches
        self._repo = repo
        self.loaded = False

    def _load(self):
        """ Read the remotenames file, store entries matching selected kind """
        self.loaded = True
        repo = self._repo
        for node, rpath, rname in logexchange.readremotenamefile(repo,
                                                                self._kind):
            name = rpath + '/' + rname
            self.potentialentries[name] = (node, rpath, name)

    def _resolvedata(self, potentialentry):
        """ Check that the node for potentialentry exists and return it """
        if not potentialentry in self.potentialentries:
            return None
        node, remote, name = self.potentialentries[potentialentry]
        repo = self._repo
        binnode = bin(node)
        # if the node doesn't exist, skip it
        try:
            repo.changelog.rev(binnode)
        except LookupError:
            return None
        # Skip closed branches
        if (self._kind == 'branches' and repo[binnode].closesbranch()):
            return None
        return [binnode]

    def __getitem__(self, key):
        if not self.loaded:
            self._load()
        val = self._fetchandcache(key)
        if val is not None:
            return val
        else:
            raise KeyError()

    def __iter__(self):
        return iter(self.potentialentries)

    def __len__(self):
        return len(self.potentialentries)

    def __setitem__(self):
        raise NotImplementedError

    def __delitem__(self):
        raise NotImplementedError

    def _fetchandcache(self, key):
        if key in self.cache:
            return self.cache[key]
        val = self._resolvedata(key)
        if val is not None:
            self.cache[key] = val
            return val
        else:
            return None

    def keys(self):
        """ Get a list of bookmark or branch names """
        if not self.loaded:
            self._load()
        return self.potentialentries.keys()

    def iteritems(self):
        """ Iterate over (name, node) tuples """

        if not self.loaded:
            self._load()

        for k, vtup in self.potentialentries.iteritems():
            yield (k, [bin(vtup[0])])

class remotenames(object):
    """
    This class encapsulates all the remotenames state. It also contains
    methods to access that state in convenient ways. Remotenames are lazy
    loaded. Whenever client code needs to ensure the freshest copy of
    remotenames, use the `clearnames` method to force an eventual load.
    """

    def __init__(self, repo, *args):
        self._repo = repo
        self.clearnames()

    def clearnames(self):
        """ Clear all remote names state """
        self.bookmarks = lazyremotenamedict("bookmarks", self._repo)
        self.branches = lazyremotenamedict("branches", self._repo)
        self._invalidatecache()

    def _invalidatecache(self):
        self._nodetobmarks = None
        self._nodetobranch = None
        self._hoisttonodes = None
        self._nodetohoists = None

    def bmarktonodes(self):
        return self.bookmarks

    def nodetobmarks(self):
        if not self._nodetobmarks:
            bmarktonodes = self.bmarktonodes()
            self._nodetobmarks = {}
            for name, node in bmarktonodes.iteritems():
                self._nodetobmarks.setdefault(node[0], []).append(name)
        return self._nodetobmarks

    def branchtonodes(self):
        return self.branches

    def nodetobranch(self):
        if not self._nodetobranch:
            branchtonodes = self.branchtonodes()
            self._nodetobranch = {}
            for name, nodes in branchtonodes.iteritems():
                for node in nodes:
                    self._nodetobranch.setdefault(node, []).append(name)
        return self._nodetobranch

    def hoisttonodes(self, hoist):
        if not self._hoisttonodes:
            marktonodes = self.bmarktonodes()
            self._hoisttonodes = {}
            hoist += '/'
            for name, node in marktonodes.iteritems():
                if name.startswith(hoist):
                    name = name[len(hoist):]
                    self._hoisttonodes[name] = node
        return self._hoisttonodes

    def nodetohoists(self, hoist):
        if not self._nodetohoists:
            marktonodes = self.bmarktonodes()
            self._nodetohoists = {}
            hoist += '/'
            for name, node in marktonodes.iteritems():
                if name.startswith(hoist):
                    name = name[len(hoist):]
                    self._nodetohoists.setdefault(node[0], []).append(name)
        return self._nodetohoists

def wrapprintbookmarks(orig, ui, repo, bmarks, **opts):
    if 'remotebookmarks' not in repo.names:
        return
    ns = repo.names['remotebookmarks']

    for name in ns.listnames(repo):
        nodes = ns.nodes(repo, name)
        if not nodes:
            continue
        node = nodes[0]

        bmarks[name] = (node, ' ', '')

    return orig(ui, repo, bmarks, **opts)

def extsetup(ui):
    extensions.wrapfunction(bookmarks, '_printbookmarks', wrapprintbookmarks)

def reposetup(ui, repo):
    if not repo.local():
        return

    repo._remotenames = remotenames(repo)
    ns = namespaces.namespace

    if ui.configbool('remotenames', 'bookmarks'):
        remotebookmarkns = ns(
            'remotebookmarks',
            templatename='remotebookmarks',
            colorname='remotebookmark',
            logfmt='remote bookmark:  %s\n',
            listnames=lambda repo: repo._remotenames.bmarktonodes().keys(),
            namemap=lambda repo, name:
                repo._remotenames.bmarktonodes().get(name, []),
            nodemap=lambda repo, node:
                repo._remotenames.nodetobmarks().get(node, []))
        repo.names.addnamespace(remotebookmarkns)

        # hoisting only works if there are remote bookmarks
        hoist = ui.config('remotenames', 'hoistedpeer')
        if hoist:
            hoistednamens = ns(
                'hoistednames',
                templatename='hoistednames',
                colorname='hoistedname',
                logfmt='hoisted name:  %s\n',
                listnames = lambda repo:
                    repo._remotenames.hoisttonodes(hoist).keys(),
                namemap = lambda repo, name:
                    repo._remotenames.hoisttonodes(hoist).get(name, []),
                nodemap = lambda repo, node:
                    repo._remotenames.nodetohoists(hoist).get(node, []))
            repo.names.addnamespace(hoistednamens)

    if ui.configbool('remotenames', 'branches'):
        remotebranchns = ns(
            'remotebranches',
            templatename='remotebranches',
            colorname='remotebranch',
            logfmt='remote branch:  %s\n',
            listnames = lambda repo: repo._remotenames.branchtonodes().keys(),
            namemap = lambda repo, name:
                repo._remotenames.branchtonodes().get(name, []),
            nodemap = lambda repo, node:
                repo._remotenames.nodetobranch().get(node, []))
        repo.names.addnamespace(remotebranchns)

@templatekeyword('remotenames', requires={'repo', 'ctx'})
def remotenameskw(context, mapping):
    """List of strings. Remote names associated with the changeset."""
    repo = context.resource(mapping, 'repo')
    ctx = context.resource(mapping, 'ctx')

    remotenames = []
    if 'remotebookmarks' in repo.names:
        remotenames = repo.names['remotebookmarks'].names(repo, ctx.node())

    if 'remotebranches' in repo.names:
        remotenames += repo.names['remotebranches'].names(repo, ctx.node())

    return templateutil.compatlist(context, mapping, 'remotename', remotenames,
                                   plural='remotenames')

@templatekeyword('remotebookmarks', requires={'repo', 'ctx'})
def remotebookmarkskw(context, mapping):
    """List of strings. Remote bookmarks associated with the changeset."""
    repo = context.resource(mapping, 'repo')
    ctx = context.resource(mapping, 'ctx')

    remotebmarks = []
    if 'remotebookmarks' in repo.names:
        remotebmarks = repo.names['remotebookmarks'].names(repo, ctx.node())

    return templateutil.compatlist(context, mapping, 'remotebookmark',
                                   remotebmarks, plural='remotebookmarks')

@templatekeyword('remotebranches', requires={'repo', 'ctx'})
def remotebrancheskw(context, mapping):
    """List of strings. Remote branches associated with the changeset."""
    repo = context.resource(mapping, 'repo')
    ctx = context.resource(mapping, 'ctx')

    remotebranches = []
    if 'remotebranches' in repo.names:
        remotebranches = repo.names['remotebranches'].names(repo, ctx.node())

    return templateutil.compatlist(context, mapping, 'remotebranch',
                                   remotebranches, plural='remotebranches')

def _revsetutil(repo, subset, x, rtypes):
    """utility function to return a set of revs based on the rtypes"""

    revs = set()
    cl = repo.changelog
    for rtype in rtypes:
        if rtype in repo.names:
            ns = repo.names[rtype]
            for name in ns.listnames(repo):
                revs.update(ns.nodes(repo, name))

    results = (cl.rev(n) for n in revs if cl.hasnode(n))
    return subset & smartset.baseset(sorted(results))

@revsetpredicate('remotenames()')
def remotenamesrevset(repo, subset, x):
    """All changesets which have a remotename on them."""
    revsetlang.getargs(x, 0, 0, _("remotenames takes no arguments"))
    return _revsetutil(repo, subset, x, ('remotebookmarks', 'remotebranches'))

@revsetpredicate('remotebranches()')
def remotebranchesrevset(repo, subset, x):
    """All changesets which are branch heads on remotes."""
    revsetlang.getargs(x, 0, 0, _("remotebranches takes no arguments"))
    return _revsetutil(repo, subset, x, ('remotebranches',))

@revsetpredicate('remotebookmarks()')
def remotebmarksrevset(repo, subset, x):
    """All changesets which have bookmarks on remotes."""
    revsetlang.getargs(x, 0, 0, _("remotebookmarks takes no arguments"))
    return _revsetutil(repo, subset, x, ('remotebookmarks',))
