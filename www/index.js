async function loadMarkdown() {
    const urlParams = new URLSearchParams(window.location.search);
    const path = urlParams.get('path');
    const contentDiv = document.getElementById('content');

    if (!path) {
        contentDiv.innerHTML = `
            <div class="error">
                <h2>No path provided</h2>
                <p>Please provide a path in the URL query string.</p>
                <p>Example: <code>?path=../campaigns/netherdeep/wiki/index.json</code> (or a .md file)</p>
            </div>
        `;
        return;
    }

    try {
        // Fetch the Markdown file. 
        // Depending on your web server setup, you might need to adjust the path mapping here.
        const response = await fetch(path);
        
        if (!response.ok) {
            throw new Error(`Failed to load file: ${response.status} ${response.statusText}`);
        }

        const markdown = await response.text();
        
        // Parse and render the Markdown content
        contentDiv.innerHTML = marked.parse(markdown);
        
        // Intercept links to load Markdown files within the viewer
        const links = contentDiv.querySelectorAll('a');
        links.forEach(link => {
            const href = link.getAttribute('href');
            if (href && !href.startsWith('http') && href.endsWith('.md')) {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    
                    // Resolve the relative path based on the current parsed file
                    // We need to resolve things like '../../wiki/characters/bob.md' 
                    // relative to 'campaigns/test/sessions/000/summary.md'
                    
                    // A simple way to handle relative resolving in browser without Node modules:
                    const currentDir = path.substring(0, path.lastIndexOf('/'));
                    let resolvedPath = href;
                    
                    if (!href.startsWith('/')) {
                        const url = new URL(href, window.location.origin + '/' + currentDir + '/');
                        resolvedPath = url.pathname.substring(1); // strip leading slash
                    }

                    window.location.search = `?path=${resolvedPath}`;
                });
            }
        });
        
        // Update the page title if a top-level heading exists
        const h1 = contentDiv.querySelector('h1');
        if (h1) {
            document.title = h1.textContent;
        }

    } catch (error) {
        contentDiv.innerHTML = `
            <div class="error">
                <h2>Error loading Markdown</h2>
                <p>${error.message}</p>
                <p>Attempted to load from path: <code>${path}</code></p>
            </div>
        `;
    }
}

// Initialize the loader when the DOM is ready
document.addEventListener('DOMContentLoaded', loadMarkdown);
