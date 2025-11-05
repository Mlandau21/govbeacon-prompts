class CSVComparisonViewer {
    constructor() {
        this.data = [];
        this.currentRowIndex = 0;
        this.initializeElements();
        this.bindEvents();
    }

    initializeElements() {
        this.fileInput = document.getElementById('csvFile');
        this.mainContent = document.getElementById('mainContent');
        this.rowSelect = document.getElementById('rowSelect');
        this.rowSelectorDropdown = document.getElementById('rowSelectorDropdown');
        this.errorMessage = document.getElementById('errorMessage');
        
        // Column elements
        this.samContent = document.getElementById('samContent');
        this.sweetspotContent = document.getElementById('sweetspotContent');
        this.highergovContent = document.getElementById('highergovContent');
        
        this.samUrl = document.getElementById('samUrl');
        this.sweetspotUrl = document.getElementById('sweetspotUrl');
        this.highergovUrl = document.getElementById('highergovUrl');
    }

    bindEvents() {
        this.fileInput.addEventListener('change', (e) => this.handleFileUpload(e));
        this.rowSelect.addEventListener('change', (e) => this.handleRowSelection(e));
        
        // Keyboard navigation
        document.addEventListener('keydown', (e) => this.handleKeyboardNavigation(e));
    }

    async handleFileUpload(event) {
        const file = event.target.files[0];
        if (!file) return;

        if (!file.name.endsWith('.csv')) {
            this.showError('Please select a CSV file');
            return;
        }

        try {
            const text = await this.readFile(file);
            const parsedData = this.parseCSV(text);
            this.validateData(parsedData);
            this.data = parsedData;
            this.displayData();
            this.hideError();
        } catch (error) {
            this.showError(error.message);
        }
    }

    readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => resolve(e.target.result);
            reader.onerror = () => reject(new Error('Failed to read file'));
            reader.readAsText(file);
        });
    }

    parseCSV(text) {
        // Parse CSV handling multi-line fields within quotes
        const rows = [];
        let currentRow = [];
        let currentField = '';
        let inQuotes = false;
        
        for (let i = 0; i < text.length; i++) {
            const char = text[i];
            const nextChar = text[i + 1];
            
            if (char === '"') {
                if (inQuotes && nextChar === '"') {
                    // Escaped quote
                    currentField += '"';
                    i++; // Skip next quote
                } else {
                    // Toggle quote state
                    inQuotes = !inQuotes;
                }
            } else if (char === ',' && !inQuotes) {
                // Field separator
                currentRow.push(currentField.trim());
                currentField = '';
            } else if ((char === '\n' || char === '\r') && !inQuotes) {
                // Row separator (handle both \n and \r\n)
                if (char === '\r' && nextChar === '\n') {
                    i++; // Skip \n in \r\n
                }
                if (currentField || currentRow.length > 0) {
                    currentRow.push(currentField.trim());
                    if (currentRow.some(field => field)) { // Only add non-empty rows
                        rows.push(currentRow);
                    }
                    currentRow = [];
                    currentField = '';
                }
            } else {
                currentField += char;
            }
        }
        
        // Add last field and row if exists
        if (currentField || currentRow.length > 0) {
            currentRow.push(currentField.trim());
            if (currentRow.some(field => field)) {
                rows.push(currentRow);
            }
        }
        
        if (rows.length < 2) {
            throw new Error('CSV file must contain at least a header and one data row');
        }

        const headers = rows[0];
        const requiredHeaders = [
            'sam-description', 'sam-url',
            'sweetspot-summary', 'sweetspot-url',
            'highergov-summary', 'highergov-url'
        ];

        const missingHeaders = requiredHeaders.filter(h => !headers.includes(h));
        if (missingHeaders.length > 0) {
            throw new Error(`Missing required columns: ${missingHeaders.join(', ')}`);
        }

        const data = [];
        for (let i = 1; i < rows.length; i++) {
            const values = rows[i];
            if (values.length === headers.length) {
                const row = {};
                headers.forEach((header, index) => {
                    row[header] = values[index] || '';
                });
                data.push(row);
            }
        }

        return data;
    }

    validateData(data) {
        if (data.length === 0) {
            throw new Error('No valid data rows found in CSV');
        }
        
        // Check for completely empty rows
        const validRows = data.filter(row => 
            row['sam-description'] || row['sweetspot-summary'] || row['highergov-summary']
        );
        
        if (validRows.length === 0) {
            throw new Error('No rows with content found in CSV');
        }
    }

    displayData() {
        this.mainContent.style.display = 'flex';
        this.rowSelectorDropdown.style.display = 'flex';
        this.renderRowDropdown();
        this.selectRow(0);
    }

    renderRowDropdown() {
        this.rowSelect.innerHTML = '<option value="">Choose a row...</option>';
        
        this.data.forEach((row, index) => {
            const option = document.createElement('option');
            option.value = index;
            option.textContent = `Row ${index + 1}`;
            
            // Mark incomplete rows
            const hasContent = row['sam-description'] || row['sweetspot-summary'] || row['highergov-summary'];
            if (!hasContent) {
                option.textContent += ' (empty)';
            }
            
            this.rowSelect.appendChild(option);
        });
    }

    handleRowSelection(event) {
        const selectedIndex = parseInt(event.target.value);
        if (!isNaN(selectedIndex)) {
            this.selectRow(selectedIndex);
        }
    }

    selectRow(index) {
        if (index < 0 || index >= this.data.length) return;
        
        this.currentRowIndex = index;
        
        // Update dropdown selection
        this.rowSelect.value = index;
        
        // Update column content
        const row = this.data[index];
        this.updateColumn('sam', row['sam-description'], row['sam-url']);
        this.updateColumn('sweetspot', row['sweetspot-summary'], row['sweetspot-url']);
        this.updateColumn('highergov', row['highergov-summary'], row['highergov-url']);
    }

    updateColumn(column, content, url) {
        const contentElement = document.getElementById(`${column}Content`);
        const urlElement = document.getElementById(`${column}Url`);
        
        // Update content
        contentElement.textContent = content || 'No content available';
        
        // Update URL
        if (url && url.trim()) {
            urlElement.href = url;
            urlElement.classList.remove('no-url');
            urlElement.textContent = 'View Source';
        } else {
            urlElement.href = '#';
            urlElement.classList.add('no-url');
            urlElement.textContent = 'No URL';
        }
    }

    handleKeyboardNavigation(event) {
        if (this.data.length === 0) return;
        
        switch (event.key) {
            case 'ArrowUp':
                event.preventDefault();
                if (this.currentRowIndex > 0) {
                    this.selectRow(this.currentRowIndex - 1);
                }
                break;
            case 'ArrowDown':
                event.preventDefault();
                if (this.currentRowIndex < this.data.length - 1) {
                    this.selectRow(this.currentRowIndex + 1);
                }
                break;
            case 'Home':
                event.preventDefault();
                this.selectRow(0);
                break;
            case 'End':
                event.preventDefault();
                this.selectRow(this.data.length - 1);
                break;
        }
    }

    showError(message) {
        this.errorMessage.textContent = message;
        this.errorMessage.style.display = 'block';
        
        // Auto-hide after 5 seconds
        setTimeout(() => this.hideError(), 5000);
    }

    hideError() {
        this.errorMessage.style.display = 'none';
    }
}

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    new CSVComparisonViewer();
});
