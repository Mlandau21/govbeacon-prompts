class DocumentSummaryViewer {
    constructor() {
        this.fileInput = document.getElementById('docCsv');
        this.rootInput = document.getElementById('rootInput');
        this.opportunitySelector = document.getElementById('opportunitySelector');
        this.opportunitySelect = document.getElementById('opportunitySelect');
        this.searchContainer = document.getElementById('searchContainer');
        this.searchInput = document.getElementById('searchInput');
        this.documentsContainer = document.getElementById('documents');
        this.statusBar = document.getElementById('statusBar');
        this.errorMessage = document.getElementById('errorMessage');

        this.documentsByOpportunity = new Map();
        this.currentOpportunity = null;
        this.filteredDocuments = [];

        this._bindEvents();
    }

    _bindEvents() {
        this.fileInput.addEventListener('change', (event) => this._handleFile(event));
        this.opportunitySelect.addEventListener('change', () => this._handleOpportunityChange());
        this.searchInput.addEventListener('input', () => this._applySearch());
        this.rootInput.addEventListener('input', () => this._renderDocuments());
    }

    _handleFile(event) {
        const file = event.target.files?.[0];
        if (!file) return;

        this._readFile(file)
            .then((text) => {
                const rows = this._parseCsv(text);
                if (!rows.length) {
                    this._showError('The selected CSV does not contain any rows.');
                    return;
                }

                this.documentsByOpportunity = this._groupByOpportunity(rows);
                if (!this.documentsByOpportunity.size) {
                    this._showError('No rows included a sam-url column.');
                    return;
                }

                this._populateOpportunitySelector();
                this._setStatus(`Loaded ${rows.length} document summaries from ${file.name}.`);
            })
            .catch((error) => this._showError(`Failed to read CSV: ${error.message}`));
    }

    _populateOpportunitySelector() {
        const entries = Array.from(this.documentsByOpportunity.entries());
        entries.sort((a, b) => a[0].localeCompare(b[0]));

        this.opportunitySelect.innerHTML = '';
        entries.forEach(([samUrl], index) => {
            const option = document.createElement('option');
            option.value = samUrl;
            option.textContent = `${index + 1}. ${samUrl}`;
            this.opportunitySelect.appendChild(option);
        });

        this.opportunitySelector.style.display = 'flex';
        this.searchContainer.style.display = 'flex';
        this.documentsContainer.style.display = 'grid';

        this.opportunitySelect.selectedIndex = 0;
        this._handleOpportunityChange();
    }

    _handleOpportunityChange() {
        const samUrl = this.opportunitySelect.value;
        if (!samUrl) {
            this.currentOpportunity = null;
            this.filteredDocuments = [];
            this._renderDocuments();
            return;
        }

        this.currentOpportunity = samUrl;
        const documents = this.documentsByOpportunity.get(samUrl) ?? [];
        this.filteredDocuments = [...documents];
        this.searchInput.value = '';
        this._renderDocuments();
        this._setStatus(`${documents.length} document(s) available for ${samUrl}`);
    }

    _applySearch() {
        if (!this.currentOpportunity) return;
        const keyword = this.searchInput.value.trim().toLowerCase();
        const documents = this.documentsByOpportunity.get(this.currentOpportunity) ?? [];

        if (!keyword) {
            this.filteredDocuments = [...documents];
        } else {
            this.filteredDocuments = documents.filter((doc) => {
                const haystack = `${doc.filename} ${doc.detected_doc_type} ${doc.summary}`.toLowerCase();
                return haystack.includes(keyword);
            });
        }

        this._renderDocuments();
        this._setStatus(`${this.filteredDocuments.length} document(s) match the current search.`);
    }

    _renderDocuments() {
        this.documentsContainer.innerHTML = '';
        if (!this.filteredDocuments.length) {
            const message = document.createElement('p');
            message.className = 'document-empty';
            message.textContent = 'No document summaries to display.';
            this.documentsContainer.appendChild(message);
            return;
        }

        const basePath = this.rootInput.value.trim();

        this.filteredDocuments.forEach((doc) => {
            const card = document.createElement('article');
            card.className = 'document-card';

            const header = document.createElement('div');
            header.className = 'document-header';

            const title = document.createElement('h2');
            title.textContent = doc.filename;
            header.appendChild(title);

            const meta = document.createElement('div');
            meta.className = 'document-meta';

            if (doc.detected_doc_type) {
                const typeTag = document.createElement('span');
                typeTag.textContent = `Detected: ${doc.detected_doc_type}`;
                meta.appendChild(typeTag);
            }

            if (doc.filetype) {
                const extensionTag = document.createElement('span');
                extensionTag.textContent = doc.filetype.toUpperCase();
                meta.appendChild(extensionTag);
            }

            header.appendChild(meta);
            card.appendChild(header);

            const pathRow = document.createElement('div');
            pathRow.className = 'document-path';
            if (doc.local_path) {
                const fileUrl = this._buildFileUrl(basePath, doc.local_path);
                if (fileUrl) {
                    const link = document.createElement('a');
                    link.href = fileUrl;
                    link.textContent = doc.local_path;
                    link.target = '_blank';
                    link.rel = 'noopener';
                    pathRow.appendChild(link);
                } else {
                    pathRow.textContent = doc.local_path;
                }
            } else {
                pathRow.textContent = 'No local path recorded.';
            }
            card.appendChild(pathRow);

            const summary = document.createElement('div');
            summary.className = 'document-summary';
            summary.innerHTML = this._parseMarkdown(doc.summary || 'No summary available.');
            card.appendChild(summary);

            this.documentsContainer.appendChild(card);
        });
    }

    _parseMarkdown(text) {
        if (!text) return '';
        
        let html = text
            // Escape HTML first to prevent XSS
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            
            // Headers (must come before bold)
            .replace(/^### (.*$)/gm, '<h3>$1</h3>')
            .replace(/^## (.*$)/gm, '<h2>$1</h2>')
            .replace(/^# (.*$)/gm, '<h1>$1</h1>')
            
            // Bold
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            
            // Italic
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            
            // Links
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
            
            // Unordered lists
            .replace(/^\- (.+)$/gm, '<li>$1</li>')
            
            // Wrap consecutive <li> in <ul>
            .replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`)
            
            // Line breaks (convert double newlines to paragraphs)
            .split('\n\n')
            .map(para => {
                if (para.startsWith('<h') || para.startsWith('<ul>') || para.startsWith('<ol>')) {
                    return para;
                }
                return para.trim() ? `<p>${para.replace(/\n/g, '<br>')}</p>` : '';
            })
            .join('\n');
        
        return html;
    }

    _buildFileUrl(root, relativePath) {
        if (!root) return null;
        const sanitizedRoot = root.replace(/\\/g, '/');
        const sanitizedRelative = relativePath.replace(/\\/g, '/');
        const base = sanitizedRoot.endsWith('/') ? sanitizedRoot.slice(0, -1) : sanitizedRoot;
        const path = `${base}/${sanitizedRelative}`;
        if (path.startsWith('file://')) {
            return encodeURI(path);
        }
        return encodeURI(`file://${path}`);
    }

    _groupByOpportunity(rows) {
        const grouped = new Map();
        rows.forEach((row) => {
            const samUrl = (row['sam-url'] || '').trim();
            if (!samUrl) return;
            const list = grouped.get(samUrl) ?? [];
            list.push(row);
            grouped.set(samUrl, list);
        });
        return grouped;
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
    new DocumentSummaryViewer();
});

