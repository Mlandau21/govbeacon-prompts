class GovBeaconCompare {
    constructor() {
        this.baseInput = document.getElementById('baseCsv');
        this.summaryInput = document.getElementById('summaryCsv');
        this.rowSelect = document.getElementById('rowSelect');
        this.rowSelectorContainer = document.getElementById('rowSelector');
        this.searchContainer = document.getElementById('searchContainer');
        this.searchInput = document.getElementById('searchInput');
        this.comparison = document.getElementById('comparison');
        this.statusBar = document.getElementById('statusBar');
        this.errorMessage = document.getElementById('errorMessage');

        this.samDescriptionEl = document.getElementById('samDescription');
        this.samUrlEl = document.getElementById('samUrl');
        this.sweetspotSummaryEl = document.getElementById('sweetspotSummary');
        this.sweetspotUrlEl = document.getElementById('sweetspotUrl');
        this.highergovSummaryEl = document.getElementById('highergovSummary');
        this.highergovUrlEl = document.getElementById('highergovUrl');
        this.govbeaconLongEl = document.getElementById('govbeaconLong');
        this.govbeaconShortEl = document.getElementById('govbeaconShort');

        this.baseRows = [];
        this.summaryRows = [];
        this.summaryMap = new Map();
        this.mergedRows = [];
        this.filteredRows = [];

        this._bindEvents();
        this._autoLoadInputCsv();
    }

    _bindEvents() {
        this.baseInput.addEventListener('change', (event) => this._handleBaseFile(event));
        this.summaryInput.addEventListener('change', (event) => this._handleSummaryFile(event));
        this.rowSelect.addEventListener('change', () => this._handleRowSelection());
        this.searchInput.addEventListener('input', () => this._applySearch());
    }

    _autoLoadInputCsv() {
        // Auto-load input.csv from the parent directory
        const inputCsvPath = '../../input.csv';
        this._setStatus('Loading input.csv...');
        
        fetch(inputCsvPath)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Failed to load input.csv: ${response.statusText}`);
                }
                return response.text();
            })
            .then(text => {
                this.baseRows = this._parseCsv(text);
                this._setStatus(`Auto-loaded ${this.baseRows.length} opportunities from input.csv`);
                this._tryMerge();
            })
            .catch(error => {
                this._setStatus('Could not auto-load input.csv. Please select files manually.');
                console.warn('Auto-load failed:', error);
            });
    }

    _handleBaseFile(event) {
        const file = event.target.files?.[0];
        if (!file) return;
        this._readFile(file)
            .then((text) => {
                this.baseRows = this._parseCsv(text);
                this._setStatus(`Loaded ${this.baseRows.length} opportunities from ${file.name}`);
                this._tryMerge();
            })
            .catch((error) => this._showError(`Failed to read base CSV: ${error.message}`));
    }

    _handleSummaryFile(event) {
        const file = event.target.files?.[0];
        if (!file) return;
        this._readFile(file)
            .then((text) => {
                this.summaryRows = this._parseCsv(text);
                this.summaryMap = new Map();
                this.summaryRows.forEach((row) => {
                    const samUrl = (row['sam-url'] || '').trim();
                    if (samUrl) {
                        this.summaryMap.set(samUrl, row);
                    }
                });
                this._setStatus(`Loaded ${this.summaryRows.length} GovBeacon summaries from ${file.name}`);
                this._tryMerge();
            })
            .catch((error) => this._showError(`Failed to read summary CSV: ${error.message}`));
    }

    _tryMerge() {
        if (!this.baseRows.length || !this.summaryRows.length) {
            return;
        }

        this.mergedRows = this.baseRows
            .map((row, index) => {
                const samUrl = (row['sam-url'] || '').trim();
                if (!samUrl) return null;
                const summaryRow = this.summaryMap.get(samUrl) ?? null;
                return {
                    index,
                    samUrl,
                    opportunityId: row['opportunity_id'] || summaryRow?.opportunity_id || `Row ${index + 1}`,
                    baseRow: row,
                    summaryRow,
                };
            })
            .filter(Boolean);

        if (!this.mergedRows.length) {
            this._showError('No overlapping sam-url entries were found between the two files.');
            return;
        }

        this.filteredRows = [...this.mergedRows];
        this._renderDropdown();
        this._applySearch();
        this.rowSelectorContainer.style.display = 'flex';
        this.searchContainer.style.display = 'flex';
        this.comparison.style.display = 'grid';

        this._setStatus(`Ready. ${this.mergedRows.length} merged opportunities available.`);
    }

    _renderDropdown() {
        this.rowSelect.innerHTML = '';
        this.filteredRows.forEach((row, idx) => {
            const option = document.createElement('option');
            option.value = String(idx);
            let label = row.baseRow['title'] || row.baseRow['sam-description']?.split('\n')[0] || row.samUrl;
            // Truncate long labels
            if (label.length > 80) {
                label = label.substring(0, 77) + '...';
            }
            option.textContent = `${idx + 1}. ${label}`;
            option.title = row.baseRow['title'] || row.baseRow['sam-description']?.split('\n')[0] || row.samUrl; // Full text in tooltip
            this.rowSelect.appendChild(option);
        });
    }

    _handleRowSelection() {
        const selectedIndex = Number.parseInt(this.rowSelect.value, 10);
        if (Number.isNaN(selectedIndex) || selectedIndex < 0 || selectedIndex >= this.filteredRows.length) {
            return;
        }
        this._displayRow(this.filteredRows[selectedIndex]);
    }

    _applySearch() {
        const keyword = this.searchInput.value.trim().toLowerCase();
        if (!keyword) {
            this.filteredRows = [...this.mergedRows];
        } else {
            this.filteredRows = this.mergedRows.filter((row) => {
                const base = JSON.stringify(row.baseRow).toLowerCase();
                const summary = row.summaryRow ? JSON.stringify(row.summaryRow).toLowerCase() : '';
                return base.includes(keyword) || summary.includes(keyword);
            });
        }

        this._renderDropdown();

        if (this.filteredRows.length) {
            this.rowSelect.selectedIndex = 0;
            this._displayRow(this.filteredRows[0]);
            this._setStatus(`${this.filteredRows.length} matching opportunities`);
        } else {
            this._clearDisplay();
            this._setStatus('No results match the current search.');
        }
    }

    _displayRow(row) {
        const { baseRow, summaryRow, samUrl } = row;

        this._setContent(this.samDescriptionEl, baseRow['sam-description'] || '—');
        this._setLink(this.samUrlEl, samUrl, 'View notice');

        this._setContent(this.sweetspotSummaryEl, baseRow['sweetspot-summary'] || '—');
        this._setLink(this.sweetspotUrlEl, baseRow['sweetspot-url'], 'View source');

        this._setContent(this.highergovSummaryEl, baseRow['highergov-summary'] || '—');
        this._setLink(this.highergovUrlEl, baseRow['highergov-url'], 'View source');

        if (summaryRow) {
            this._setContent(this.govbeaconLongEl, summaryRow['govbeacon-long-summary'] || 'No GovBeacon long summary.');
            this._setContent(this.govbeaconShortEl, summaryRow['govbeacon-short-summary'] || 'No GovBeacon short summary.');
        } else {
            this._setContent(this.govbeaconLongEl, 'No GovBeacon summary available for this opportunity.');
            this._setContent(this.govbeaconShortEl, '');
        }
    }

    _clearDisplay() {
        this._setContent(this.samDescriptionEl, '');
        this._setLink(this.samUrlEl, '', 'View notice');
        this._setContent(this.sweetspotSummaryEl, '');
        this._setLink(this.sweetspotUrlEl, '', 'View source');
        this._setContent(this.highergovSummaryEl, '');
        this._setLink(this.highergovUrlEl, '', 'View source');
        this._setContent(this.govbeaconLongEl, '');
        this._setContent(this.govbeaconShortEl, '');
    }

    _setContent(element, value) {
        if (!element) return;
        const text = value || '';
        element.innerHTML = this._parseMarkdown(text);
    }

    _parseMarkdown(text) {
        if (!text) return '';
        
        // Step 1: Escape HTML first to prevent XSS
        let html = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        
        // Step 2: Process headers (must come before bold to avoid conflicts)
        html = html
            .replace(/^#### (.*)$/gm, '<h4>$1</h4>')
            .replace(/^### (.*)$/gm, '<h3>$1</h3>')
            .replace(/^## (.*)$/gm, '<h2>$1</h2>')
            .replace(/^# (.*)$/gm, '<h1>$1</h1>');
        
        // Step 3: Process lists FIRST (before inline formatting to avoid conflicts with list markers)
        // Extract list items, process their content for formatting, then restore as HTML lists
        const listPlaceholders = [];
        let placeholderIndex = 0;
        
        // Helper function to process inline formatting on content
        const processInlineFormatting = (text) => {
            return text
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*([^*\s]+[^*]*[^*\s]+)\*/g, '<em>$1</em>') // Only match *text* with actual content
                .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
        };
        
        // Replace unordered list items with placeholders (process content first)
        html = html.replace(/^(\s*)([\*\-])\s+(.+)$/gm, (match, indent, marker, content) => {
            const placeholder = `__LIST_ITEM_${placeholderIndex}__`;
            const formattedContent = processInlineFormatting(content);
            listPlaceholders[placeholderIndex] = { type: 'ul', content: formattedContent, indent };
            placeholderIndex++;
            return `${indent}${placeholder}`;
        });
        
        // Replace ordered list items with placeholders (process content first)
        html = html.replace(/^(\s*)(\d+)\.\s+(.+)$/gm, (match, indent, number, content) => {
            const placeholder = `__LIST_ITEM_${placeholderIndex}__`;
            const formattedContent = processInlineFormatting(content);
            listPlaceholders[placeholderIndex] = { type: 'ol', content: formattedContent, indent, number };
            placeholderIndex++;
            return `${indent}${placeholder}`;
        });
        
        // Step 4: Process inline formatting on remaining text (non-list content)
        html = html
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*([^*\s]+[^*]*[^*\s]+)\*/g, '<em>$1</em>') // Only match *text* with actual content, not just spaces
        
        // Step 5: Process links on remaining text
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
        
        // Step 6: Restore list items and process lists
        const lines = html.split('\n');
        const processedLines = [];
        let inUnorderedList = false;
        let inOrderedList = false;
        
        for (let i = 0; i < lines.length; i++) {
            let line = lines[i];
            
            // Check for list item placeholders
            const placeholderMatch = line.match(/^(\s*)__LIST_ITEM_(\d+)__$/);
            if (placeholderMatch) {
                const placeholder = listPlaceholders[parseInt(placeholderMatch[2])];
                if (!placeholder) {
                    processedLines.push(line);
                    continue;
                }
                
                if (placeholder.type === 'ul') {
                    if (!inUnorderedList) {
                        if (inOrderedList) {
                            processedLines.push('</ol>');
                            inOrderedList = false;
                        }
                        processedLines.push('<ul>');
                        inUnorderedList = true;
                    }
                    processedLines.push(`<li>${placeholder.content}</li>`);
                } else if (placeholder.type === 'ol') {
                    if (!inOrderedList) {
                        if (inUnorderedList) {
                            processedLines.push('</ul>');
                            inUnorderedList = false;
                        }
                        processedLines.push('<ol>');
                        inOrderedList = true;
                    }
                    processedLines.push(`<li>${placeholder.content}</li>`);
                }
                continue;
            }
            
            // Not a list item - close any open lists
            if (inUnorderedList) {
                processedLines.push('</ul>');
                inUnorderedList = false;
            }
            if (inOrderedList) {
                processedLines.push('</ol>');
                inOrderedList = false;
            }
            
            processedLines.push(line);
        }
        
        // Close any remaining open lists
        if (inUnorderedList) processedLines.push('</ul>');
        if (inOrderedList) processedLines.push('</ol>');
        
        html = processedLines.join('\n');
        
        // Step 7: Process paragraphs (split on double newlines)
        const paragraphs = html.split(/\n\n+/);
        html = paragraphs.map(para => {
            para = para.trim();
            if (!para) return '';
            
            // If already has block-level HTML tags, don't wrap in <p>
            if (para.match(/^<(h[1-6]|ul|ol|li|p|div|blockquote|pre)/)) {
                // Convert single newlines to <br> within block elements (but not in lists)
                if (!para.match(/^<(ul|ol)/)) {
                    return para.replace(/\n/g, '<br>');
                }
                return para;
            }
            
            // Regular paragraph: convert single newlines to <br> and wrap in <p>
            return `<p>${para.replace(/\n/g, '<br>')}</p>`;
        }).join('\n');
        
        return html;
    }

    _setLink(anchor, url, fallbackLabel) {
        if (!anchor) return;
        const trimmed = (url || '').trim();
        if (trimmed) {
            anchor.href = trimmed;
            anchor.textContent = fallbackLabel;
            anchor.classList.remove('no-link');
        } else {
            anchor.href = '#';
            anchor.textContent = 'No link';
            anchor.classList.add('no-link');
        }
    }

    _setStatus(message) {
        if (this.statusBar) {
            this.statusBar.textContent = message;
        }
        this._hideError();
    }

    _showError(message) {
        if (!this.errorMessage) return;
        this.errorMessage.textContent = message;
        this.errorMessage.style.display = 'block';
    }

    _hideError() {
        if (!this.errorMessage) return;
        this.errorMessage.style.display = 'none';
    }

    _readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (event) => resolve(event.target?.result ?? '');
            reader.onerror = () => reject(new Error('Unable to read file.'));
            reader.readAsText(file);
        });
    }

    _parseCsv(text) {
        const rows = [];
        const headers = [];
        let currentField = '';
        let currentRow = [];
        let inQuotes = false;

        const pushField = () => {
            currentRow.push(currentField.trim());
            currentField = '';
        };

        const pushRow = () => {
            if (!currentRow.length) return;
            if (!headers.length) {
                headers.push(...currentRow);
            } else if (currentRow.length === headers.length) {
                const row = {};
                headers.forEach((header, index) => {
                    row[header] = currentRow[index] ?? '';
                });
                rows.push(row);
            }
            currentRow = [];
        };

        for (let i = 0; i < text.length; i += 1) {
            const char = text[i];
            const next = text[i + 1];

            if (char === '"') {
                if (inQuotes && next === '"') {
                    currentField += '"';
                    i += 1;
                } else {
                    inQuotes = !inQuotes;
                }
            } else if (char === ',' && !inQuotes) {
                pushField();
            } else if ((char === '\n' || char === '\r') && !inQuotes) {
                if (char === '\r' && next === '\n') {
                    i += 1;
                }
                pushField();
                pushRow();
            } else {
                currentField += char;
            }
        }

        if (currentField || currentRow.length) {
            pushField();
            pushRow();
        }

        return rows;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new GovBeaconCompare();
});

