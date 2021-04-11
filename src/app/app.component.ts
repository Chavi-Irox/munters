import { Component } from '@angular/core';
import { Book } from './models/book.model';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss']
})
export class AppComponent {
  selectedBook: Book;
  updatesBookData:Book;
  title = 'library';

  onBookSelected(book: Book) {
    this.selectedBook = book;
  }

  onBookDataSaved(bookData){
    this.updatesBookData = bookData;
  }
}
