# CSV Comparison Viewer

A browser-based application for comparing three text columns from CSV data side-by-side. Designed specifically for viewing SAM descriptions, Sweetspot summaries, and HigherGov summaries with their associated source URLs.

## Features

- **3-Column Comparison View**: Side-by-side display of sam-description, sweetspot-summary, and highergov-summary
- **URL Integration**: Clickable source links at the top of each column
- **Dropdown Row Selection**: Compact row selector in header for easy navigation (supports ~50+ rows)
- **Full-Width Layout**: Maximum space utilization for comparison content
- **Responsive Design**: Adapts to window size with mobile-friendly layout
- **Keyboard Navigation**: Arrow keys, Home, and End keys for quick row selection
- **11px Font Size**: Optimized for content density while maintaining readability
- **CSV Validation**: Ensures required columns are present and data is properly formatted

## Requirements

The CSV file must contain these exact columns:
- `sam-description`
- `sam-url`
- `sweetspot-summary`
- `sweetspot-url`
- `highergov-summary`
- `highergov-url`

## Usage

1. **Start the application**:
   ```bash
   # Navigate to the project directory
   cd /path/to/govbeacon-prompts
   
   # Start a local HTTP server
   python3 -m http.server 8000
   ```

2. **Open in browser**:
   - Navigate to `http://localhost:8000`
   - Click "Choose CSV File" and select your CSV file

3. **Navigate rows**:
   - Use the dropdown selector in the header to choose a row
   - Use keyboard arrows (↑/↓) to move between rows
   - Press Home to go to the first row, End for the last row

4. **View source URLs**:
   - Click "View Source" links at the top of each column
   - Links will open in new tabs if available

## File Structure

```
govbeacon-prompts/
├── index.html          # Main application HTML
├── styles.css          # Responsive styling and layout
├── app.js             # Application logic and CSV parsing
├── input.csv          # Sample data file
└── README.md          # This documentation
```

## Technical Implementation

- **Pure HTML/CSS/JavaScript**: No external dependencies required
- **CSV Parsing**: Custom parser handling multi-line quoted fields and commas
- **State Management**: Simple class-based state for data and selection
- **Responsive Grid**: CSS Grid for full-width 3-column layout, flexbox for mobile
- **Header Controls**: Dropdown row selector and file upload in compact header
- **Error Handling**: User-friendly error messages for invalid files

## Browser Compatibility

- Chrome/Edge 88+
- Firefox 85+
- Safari 14+
- Modern browsers with ES6 support

## Development

The application is built with vanilla JavaScript and requires no build process. Simply open `index.html` in a browser or serve via HTTP server.

For local development with live reload, you can use any static server tool:
```bash
# Using Python
python3 -m http.server 8000

# Using Node.js (if available)
npx serve .

# Using PHP
php -S localhost:8000
```

## Sample Data Format

```csv
sam-description,sam-url,sweetspot-summary,sweetspot-url,highergov-summary,highergov-url
"Sample description text","https://example.com/sam","Sample summary","https://example.com/sweetspot","Sample higherGov","https://example.com/highergov"
```

## Troubleshooting

- **File not loading**: Ensure the CSV file has all required columns
- **Display issues**: Check that you're accessing via HTTP server, not file:// protocol
- **Empty rows**: Rows with no content in any text column are marked as "empty" but still selectable
