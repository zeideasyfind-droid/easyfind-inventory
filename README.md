# EasyFind Inventory Engine

## Duplicate handling
- URLs are canonicalized before matching.
- Duplicate detection uses a confidence-based score across canonical URL, portal, society, location, contact, BHK, area, rent, deposit, floor, and a stable internal property fingerprint.
- PID is reused whenever a definite or likely duplicate is detected; the fingerprint is internal only and is not written to the sheet.
