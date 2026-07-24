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
                    const currentDir = path.substring(0, path.lastIndexOf('/'));
                    let resolvedPath = href;
                    
                    if (!href.startsWith('/')) {
                        const url = new URL(href, window.location.origin + '/' + currentDir + '/');
                        resolvedPath = url.pathname.substring(1); // strip leading slash
                    }

                    // Use history.pushState to navigate without a full page reload
                    const newUrl = new URL(window.location);
                    newUrl.searchParams.set('path', resolvedPath);
                    window.history.pushState({path: resolvedPath}, '', newUrl);
                    
                    // Trigger the load without reloading the page
                    window.dispatchEvent(new Event('popstate'));
                });
            }
        });
        
        // Update the page title if a top-level heading exists
        const h1 = contentDiv.querySelector('h1');
        if (h1) {
            document.title = h1.textContent;
        }

        // Only load the sidebar if it hasn't been loaded or if we changed campaigns completely
        let campaignWikiDir = '';
        const wikiMatch = path.match(/^(.*?wiki\/)/);
        if (wikiMatch) {
            campaignWikiDir = wikiMatch[1];
        } else {
            const campaignMatch = path.match(/^(.*?campaigns\/[^\/]+\/)/);
            if (campaignMatch) {
                campaignWikiDir = campaignMatch[1] + 'wiki/';
            }
        }
        
        const navContent = document.getElementById('nav-content');
        if (!window.loadedCampaignWikiDir || window.loadedCampaignWikiDir !== campaignWikiDir) {
            await loadSidebar(path, campaignWikiDir);
            window.loadedCampaignWikiDir = campaignWikiDir;
        } else {
            // Update active state in sidebar without full reload
            updateSidebarActiveState(path);
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

function updateSidebarActiveState(currentPath) {
    const navContent = document.getElementById('nav-content');
    
    // Remove previous active classes
    const oldActiveList = navContent.querySelectorAll('a.active');
    oldActiveList.forEach(el => el.classList.remove('active'));
    
    // Find new active link and select it
    const links = navContent.querySelectorAll('a');
    let newActiveLink = null;
    links.forEach(link => {
        const href = link.getAttribute('href');
        if (href && href.includes(`path=${currentPath}`)) {
            newActiveLink = link;
            link.classList.add('active');
        }
    });

    // Expand the group containing the active page if not already expanded
    if (newActiveLink) {
        const parentUl = newActiveLink.closest('ul.nested');
        if (parentUl && parentUl.style.display !== 'block') {
            parentUl.style.display = 'block';
            const parentStrong = parentUl.previousElementSibling;
            if (parentStrong && parentStrong.classList.contains('collapsible')) {
                parentStrong.classList.add('active-collapse');
            }
        }
    }
}

async function loadSidebar(currentPath, campaignWikiDir) {
    const navContent = document.getElementById('nav-content');
    if (!campaignWikiDir) {
        navContent.innerHTML = 'Navigation unavailable (cannot determine campaign wiki dir).';
        return;
    }

    const indexPath = campaignWikiDir + 'index.json';
    try {
        const response = await fetch(indexPath);
        if (!response.ok) {
            navContent.innerHTML = 'Navigation unavailable.';
            return;
        }
        
        const indexData = await response.json();
        const entities = indexData.entities;
        
        // Group by folder (e.g. 'characters', 'locations')
        const grouped = {};
        for (const [key, relativePath] of Object.entries(entities)) {
            const parts = relativePath.split('/');
            const groupName = parts.length > 1 ? parts[0] : 'other';
            const fileName = parts.length > 1 ? parts.slice(1).join('/') : relativePath;
            
            if (!grouped[groupName]) {
                grouped[groupName] = [];
            }
            
            grouped[groupName].push({
                key: key,
                name: key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
                path: campaignWikiDir + relativePath,
                relativePath: relativePath
            });
        }
        

        let html = '<ul>';

        // Find sessions by querying the server's directory listing for the sessions folder
        const sessionsDirUrl = campaignWikiDir.replace('wiki/', 'sessions/');
        let sessionsHtml = '<li><strong class="collapsible">Sessions</strong><ul class="nested">';
        
        try {
            const sessionsResponse = await fetch(sessionsDirUrl);
            if (sessionsResponse.ok) {
                const sessionsHtmlText = await sessionsResponse.text();
                // Parse the directory listing HTML to find session directories
                const parser = new DOMParser();
                const doc = parser.parseFromString(sessionsHtmlText, 'text/html');
                const links = Array.from(doc.querySelectorAll('li a'));
                
                let foundSessions = false;
                for (const link of links) {
                    const sessionDirAttr = link.getAttribute('href');
                    
                    // Look for valid session directories like '001/', '002/', etc.
                    const sessionMatch = sessionDirAttr.match(/^(\d+)\/$/);
                    if (sessionMatch) {
                        foundSessions = true;
                        const sessionId = sessionMatch[1];
                        const summaryPath = sessionsDirUrl + sessionId + '/summary.md';
                        // also fetch session_info.json if possible to parse the title, or fallback to session_id
                        let title = `Session ${parseInt(sessionId, 10)}`;
                        try {
                            const infoResponse = await fetch(sessionsDirUrl + sessionId + '/session_info.json');
                            if (infoResponse.ok) {
                                const infoJson = await infoResponse.json();
                                if (infoJson.title) {
                                    title += `: ${infoJson.title}`;
                                }
                            }
                        } catch (e) {
                            // ignore, fallback to default title
                        }
                        
                        sessionsHtml += `<li><a href="?path=${summaryPath}">${title}</a></li>`;
                    }
                }
                
                if (!foundSessions) {
                    sessionsHtml += `<li><em>(No sessions found)</em></li>`;
                }
            } else {
                throw new Error("Cannot read directory");
            }
        } catch (error) {
             console.log("Failed to inspect sessions directory index. Falling back to static check...", error);
             sessionsHtml += `<li><em>(Check sessions directory)</em></li>`;
        }
        sessionsHtml += '</ul></li>';
        html += sessionsHtml;
        
        for (const group of Object.keys(grouped).sort()) {
            html += `<li><strong class="collapsible">${group.charAt(0).toUpperCase() + group.slice(1)}</strong><ul class="nested">`;
            
            // Sort items alphabetically
            grouped[group].sort((a, b) => a.name.localeCompare(b.name));
            
            for (const item of grouped[group]) {
                html += `<li><a href="?path=${item.path}">${item.name}</a></li>`;
            }
            html += '</ul></li>';
        }
        html += '</ul>';
        
        navContent.innerHTML = html;

        // Add event listeners for collapsibles
        const collapsibles = document.querySelectorAll('.collapsible');
        collapsibles.forEach(collapsible => {
            collapsible.addEventListener('click', function() {
                this.classList.toggle('active-collapse');
                const content = this.nextElementSibling;
                if (content.style.display === 'block') {
                    content.style.display = 'none';
                } else {
                    content.style.display = 'block';
                }
            });
        });

        // Intercept links in the sidebar to prevent full reload
        navContent.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const url = new URL(link.href);
                const resolvedPath = url.searchParams.get('path');
                
                window.history.pushState({path: resolvedPath}, '', url);
                window.dispatchEvent(new Event('popstate'));
            });
        });

        // Update the active state and expand
        updateSidebarActiveState(currentPath);
        
    } catch (error) {
        console.error("Failed to load nav:", error);
        navContent.innerHTML = 'Error loading navigation.';
    }
}

// Listen for popstate events (e.g. forward/back buttons or pushState calls) to re-render without reloading the page
window.addEventListener('popstate', (e) => {
    loadMarkdown();
});

// Initialize the loader when the DOM is ready
document.addEventListener('DOMContentLoaded', loadMarkdown);
