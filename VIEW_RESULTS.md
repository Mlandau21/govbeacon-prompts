# How to View Full Run Results

## Quick Start

A web server is already running at `http://localhost:8000`. Follow the steps below to view different aspects of your results.

---

## Method 1: View Opportunity Summaries (High-Level Overview)

This shows the GovBeacon-generated summaries for each opportunity.

### Steps:

1. **Open the comparison viewer:**
   - Navigate to: `http://localhost:8000/viewer/compare/`

2. **Load the input data:**
   - Click "Load input.csv"
   - Select: `/Users/matt/Desktop/govbeacon-prompts/input.csv`

3. **Load the GovBeacon summaries:**
   - Click "Load sam-summary CSV"
   - Select: `/Users/matt/Desktop/govbeacon-prompts/outputs/full-run/opportunity_summaries/sam-summary-gemini-flash-lite-latest-20251105-045453.csv`

4. **View results:**
   - Use the dropdown to select an opportunity
   - You'll see side-by-side comparisons:
     - **SAM Description** (original)
     - **Sweetspot Summary** (if available)
     - **HigherGov Summary** (if available)
     - **GovBeacon Long Summary** (AI-generated)
     - **GovBeacon Short Summary** (AI-generated)

5. **Navigate:**
   - Use the dropdown to switch between opportunities
   - Use the search box to filter by keyword

---

## Method 2: View Document Summaries (Attachment-Level Details)

This shows summaries for each individual document/attachment within opportunities.

### Steps:

1. **Open the document viewer:**
   - Navigate to: `http://localhost:8000/viewer/docs/`

2. **Load the document summaries:**
   - Click "Load doc-summaries CSV"
   - Select: `/Users/matt/Desktop/govbeacon-prompts/outputs/full-run/doc_summaries/doc-summaries-gemini-flash-lite-latest-20251105-045423.csv`

3. **Set attachments path (optional, for file links):**
   - In "Attachments root" field, enter:
     ```
     /Users/matt/Desktop/govbeacon-prompts/outputs/full-run/attachments
     ```
   - This enables clickable links to the actual attachment files

4. **View results:**
   - Use the dropdown to select an opportunity
   - You'll see all document summaries for that opportunity
   - Each card shows:
     - Filename
     - Detected document type
     - File type (PDF, DOCX, etc.)
     - Local file path (clickable if attachments path is set)
     - AI-generated summary

5. **Search:**
   - Use the search box to filter documents by keyword
   - Searches across filename, document type, and summary text

---

## Method 3: View Raw CSV Files

For programmatic analysis or spreadsheet viewing:

### Available Files:

1. **Opportunity Summaries:**
   - Location: `outputs/full-run/opportunity_summaries/sam-summary-gemini-flash-lite-latest-20251105-045453.csv`
   - Columns: `sam-url`, `govbeacon-long-summary`, `govbeacon-short-summary`, `model`, `run_id`

2. **Document Summaries:**
   - Location: `outputs/full-run/doc_summaries/doc-summaries-gemini-flash-lite-latest-20251105-045423.csv`
   - Columns: `sam-url`, `opportunity_id`, `filename`, `filetype`, `local_path`, `detected_doc_type`, `summary`, `model`, `run_id`

3. **Metadata:**
   - Location: `outputs/full-run/metadata/sam-metadata.csv`
   - Contains original SAM.gov metadata

### To View in Excel/Numbers/Spreadsheet:

1. Open the CSV file directly in your spreadsheet application
2. Or use the command line:
   ```bash
   # View first few lines
   head -n 20 outputs/full-run/opportunity_summaries/sam-summary-gemini-flash-lite-latest-20251105-045453.csv
   ```

---

## Method 4: View Downloaded Attachments

The actual attachment files are stored in:

```
outputs/full-run/attachments/
```

Each opportunity has its own folder (named by opportunity ID). You can:
- Browse the folders directly in Finder
- Click file links in the document viewer (Method 2) if you set the attachments path

---

## Summary of What You Have

### Full Run Results (`outputs/full-run/`):

- **Opportunity Summaries**: 1 CSV file with AI-generated long and short summaries for each opportunity
- **Document Summaries**: 1 CSV file with AI-generated summaries for each attachment/document
- **Attachments**: Downloaded files organized by opportunity ID
- **Metadata**: Original SAM.gov metadata
- **Manifest**: JSON manifest of the run

### Quick Stats:

- **Total Opportunities**: Check the opportunity summaries CSV (should be ~385 based on input.csv)
- **Total Documents**: Check the document summaries CSV (currently 872 document summaries)
- **Run Date**: November 5, 2025 (20251105)

---

## Troubleshooting

### Web Server Not Running?

If you need to restart the server:
```bash
cd /Users/matt/Desktop/govbeacon-prompts
python3 -m http.server 8000
```

### File Links Not Working?

- Make sure you've set the correct absolute path in the "Attachments root" field
- Path should be: `/Users/matt/Desktop/govbeacon-prompts/outputs/full-run/attachments`
- File links use `file://` protocol and may require browser permissions

### CSV Not Loading?

- Check that the file path is correct
- Ensure the CSV file has the expected columns (check the headers)
- Some browsers may have file size limits for local file uploads

---

## Next Steps

1. **Review opportunities**: Use Method 1 to see high-level summaries
2. **Drill into documents**: Use Method 2 to see detailed attachment summaries
3. **Export data**: Use Method 3 to work with CSV files in other tools
4. **Access files**: Use Method 4 to view the actual downloaded attachments

