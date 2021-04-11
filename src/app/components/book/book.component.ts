import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnDestroy, OnInit, Output, ViewEncapsulation } from '@angular/core';
import { DEFAULT_IMG } from 'src/app/app.consts';
import { Book } from 'src/app/models/book.model';
import { BooksService } from 'src/app/services/books.service';

@Component({
  selector: 'app-book',
  templateUrl: './book.component.html',
  styleUrls: ['./book.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None
})
export class BookComponent implements OnInit, OnDestroy {
  @Input() bookData: Book;
  @Input() addMode: boolean;
  @Output() bookDataSaved = new EventEmitter<Book>();
  DEFAULT_IMG = DEFAULT_IMG;
  subsribers: any[] = [];
  constructor(private booksService: BooksService) { }

  ngOnInit(): void {
  }

  onSubmit() {
    if (this.bookData.CatalogId) {
      this.subsribers.push(this.booksService.updateBook(this.bookData).subscribe(res => {
        this.bookDataSaved.emit(res);
        this.bookData = res;
      }))
    } else {
      this.subsribers.push(this.booksService.addBook(this.bookData).subscribe(res => {
        this.bookDataSaved.emit(res);
        this.bookData = res;
      }))
    }
  }

  ngOnDestroy(): void {
    this.subsribers.forEach(subscribe => {
      subscribe.unsubscribe();
    });
  }

}
