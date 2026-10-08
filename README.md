# PrintEase Cloud Online v1

This is the **internet/cloud-ready** PrintEase starter. It is designed for:

Student phone (campus Wi-Fi/mobile data) -> Internet -> PrintEase server -> Internet -> Shop PC browser.

## Included
- Student registration/login
- Online print order submission
- PDF page-count detection on the server
- PDF/DOC/DOCX/PPT/PPTX/XLS/XLSX/CSV/TXT upload
- B&W / Color, Single / Double, A4 / A3
- Automatic price calculation
- ₹5 service charge for regular users
- Free service charge for members
- 50% first-order discount
- Token generation
- Student order history and live status polling
- Shop admin dashboard
- Waiting -> Printing -> Ready -> Collected / Cancelled
- Paid / Unpaid flag
- Editable shop rates
- Daily order/revenue/page statistics
- 50 MB upload limit

## Local test
1. Install Python 3.10+.
2. Open a command prompt in this folder.
3. Run: `pip install -r requirements.txt`
4. Run: `python app.py`
5. Student page: http://127.0.0.1:8080
6. Admin page: http://127.0.0.1:8080/admin

Default admin is `admin / admin123`. **Change it before public deployment.**

## Important before public deployment
This package is a strong prototype/starter, not a finished payment/notification product. For public daily use, deploy behind HTTPS with a persistent server/storage, change the admin password and secret, and add a real payment gateway and notification provider. SQLite + local uploads are fine for testing or a small single-server deployment with persistent disk, but should be migrated to managed database/object storage as the business grows.

## Office page counts
PDF page counts are detected with pypdf. Word/PowerPoint/Excel page counts are not reliably determined by a browser or file container alone because printer settings affect pagination. The order screen therefore allows the shop to verify/adjust the page count before printing.

## Deployment shape
- Public student URL: `/`
- Shop admin URL: `/admin`
- Shop PC only needs a browser once the server is online.
