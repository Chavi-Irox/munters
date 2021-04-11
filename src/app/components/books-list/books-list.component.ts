import { ChangeDetectionStrategy, ChangeDetectorRef, Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges, ViewEncapsulation } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators'
import { Book } from 'src/app/models/book.model';
import { BooksService } from 'src/app/services/books.service';

@Component({
  selector: 'app-books-list',
  templateUrl: './books-list.component.html',
  styleUrls: ['./books-list.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None
})
export class BooksListComponent implements OnInit, OnDestroy, OnChanges {
  @Output() bookSelected = new EventEmitter<Book>();

  @Input() updatedData: Book;
  booksList$: Observable<Book[]>;
  _selectedBook: Book;
  get selectedBook(): Book {
    return this._selectedBook
  }
  set selectedBook(value: Book) {
    this._selectedBook = value;
    this.bookSelected.emit(value);
  }

  _filterTxt: string;
  get filterTxt(): string {
    return this._filterTxt
  }
  set filterTxt(value: string) {
    this._filterTxt = value;
    this.filterBookByName();
  }

  subsribers: any[] = [];

  constructor(private booksService: BooksService, private cdr: ChangeDetectorRef) {
    this.booksList$ = this.booksService.getBooksList();

  }
  ngOnChanges(changes: SimpleChanges): void {
    if (changes.updatedData.currentValue) {
      this.booksList$ = this.booksList$.pipe(map(res => {
        let index = res.findIndex(x => x.CatalogId === this.selectedBook.CatalogId);
        res[index] = changes.updatedData.currentValue;
        return res;
      }));
      this.selectedBook = changes.updatedData.currentValue;
    }
    this.filterBookByName();
  }

  ngOnInit(): void {
  }

  BookClicked(clickedBook: Book) {
    if (this.selectedBook && this.selectedBook.CatalogId === clickedBook.CatalogId) {
      this.selectedBook = null;
    } else {
      this.selectedBook = clickedBook;
    }
  }

  filterBookByName() {
    this.booksList$ = this.booksList$.pipe(map(res => {
      if (!this.filterTxt || this.filterTxt === '') {
        return res;
      }
      return res.filter(book => book.Name.toLowerCase().includes(this.filterTxt.toLowerCase()));
    }));
  }

  addBook() {
    // TODO declare defaults values
    // TODO disabled added book when there is unsaved book
    let newBook = new Book();
    this.booksList$ = this.booksList$.pipe(map(res => {
      res.push(newBook)
      return res;
    }));
    this.selectedBook = newBook;
  }

  deleteBook(deletedBook: Book) {
    this.subsribers.push(this.booksService.deleteBook(deletedBook.CatalogId).subscribe(res => {
      this.booksList$ = this.booksList$.pipe(map(res => {
        return res.filter(book => book.CatalogId !== deletedBook.CatalogId);
      }));
      if (this.selectedBook.CatalogId === deletedBook.CatalogId) {
        this.selectedBook = null;
      }
    }))

  }

  ngOnDestroy(): void {
    this.subsribers.forEach(subscribe => {
      subscribe.unsubscribe();
    });
  }

}
