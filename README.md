Price Tracker (Web Scraper Demo)

This is a small FastAPI web app that demonstrates web scraping in a clean and safe way. You paste a product link, the app attempts to extract the product title and price, and it stores the result locally so you can see what was tracked.

This project is meant as a web scraping and backend demo, not a “bypass every website” tool. Many large retail sites block scrapers, so this app focuses on showing a correct scraping workflow, good error handling, and a working web interface.

The scraper reliably works with the demo site books.toscrape.com. For other sites, the app will either extract data if possible or return a clear message instead of crashing.

To run locally, install the requirements and start the server with uvicorn. Then open the local URL in your browser and try pasting a supported link.

This project uses FastAPI, Jinja templates, requests, and BeautifulSoup.