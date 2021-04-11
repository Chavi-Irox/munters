
export class Book {
    CatalogId: Number;
    AuthorName: String;
    Name: String;
    PublicationDate: Date;
    CoverPhoto: String;
    constructor(CatalogId?, Name?, AuthorName?, PublicationDate?, CoverPhoto?) {
        this.CatalogId = CatalogId;
        this.AuthorName = AuthorName;
        this.Name = Name;
        this.PublicationDate = new Date(PublicationDate);
        this.CoverPhoto = CoverPhoto;
    }
}