import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Book } from '../models/book.model';
import { SERVER_URL } from '../app.consts';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class BooksService {
  booksList: Book[];
  index = 1000;
  constructor(private http: HttpClient) {

  }

  getBooksList(): Observable<Book[]> {
    return this.http.get<Book[]>(SERVER_URL + 'server-data/books.json');
  }

  deleteBook(bookId) {
    // TODO: this.http.delete
    return new Observable<any>(obser => {
      obser.next();
      obser.complete();
    });
  }

  addBook(newBook: Book) {
    // TODO: this.http.post
    return new Observable<any>(obser => {
      // random Id need to be in db
      newBook.CatalogId = this.index++;
      obser.next(newBook);
      obser.complete();
    });
  }

  updateBook(updatedBook: Book) {
    // TODO: this.http.put
    return new Observable<any>(obser => {
      obser.next(updatedBook);
      obser.complete();
    });
  }
}
