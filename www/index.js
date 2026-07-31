async function loadMarkdown() {
    const urlParams = new URLSearchParams(window.location.search);
    const path = urlParams.get('path');
    const contentDiv = document.querySelector('.content-wrapper');

    if (!path) {
        try {
            const campsResponse = await fetch('campaigns/');
            if (campsResponse.ok) {
                const campsHtml = await campsResponse.text();
                const parser = new DOMParser();
                const doc = parser.parseFromString(campsHtml, 'text/html');
                // Broaden the selector since remote servers like Apache/Nginx often don't put directory links inside <li> tags
                const links = Array.from(doc.querySelectorAll('a'));
                
                let campsList = '<ul style="font-size: 1.2rem; line-height: 2;">';
                let foundCampaigns = false;
                for (const link of links) {
                    const href = link.getAttribute('href');
                    if (href && href.endsWith('/') && !href.startsWith('.')) {
                        foundCampaigns = true;
                        const campName = decodeURIComponent(href.replace(/\//g, ''));
                        campsList += `<li><a href="index.html?path=campaigns/${href}wiki/index.json"><strong>${campName}</strong></a></li>`;
                    }
                }
                campsList += '</ul>';
                
                contentDiv.innerHTML = `
                    <div class="campaigns-list">
                        <h1>Select a Campaign</h1>
                        ${foundCampaigns ? campsList : '<p>No campaigns found.</p>'}
                    </div>
                `;
                document.title = "Campaigns - Bardic Aspiration";
                document.getElementById('nav-content').innerHTML = 'Select a campaign to view its contents.';
            } else {
                throw new Error("Could not load /campaigns/");
            }
        } catch (e) {
            contentDiv.innerHTML = `
                <div class="error">
                    <h2>Welcome to Bardic Aspiration</h2>
                    <p>No path provided and could not automatically list campaigns.</p>
                    <p>Example: <code>?path=campaigns/netherdeep/wiki/index.json</code></p>
                </div>
            `;
        }
        return;
    }

    try {
        const isSessionPage = window.location.pathname.endsWith('session.html');
        // Check if the user is just clicking a campaign link that points to index.json
        // In that case, we don't want to render the raw JSON text as a markdown document
        let isIndexJson = path.endsWith('index.json');
        
        // Fetch the file. 
        // Depending on your web server setup, you might need to adjust the path mapping here.
        const response = await fetch(path);
        
        if (!response.ok) {
            throw new Error(`Failed to load file: ${response.status} ${response.statusText}`);
        }

        const rawContent = await response.text();
        
        let renderedHtml = "";
        
        if (isIndexJson) {
            // We just want a blank welcome screen while the sidebar handles everything implicitly
            const campaignMatch = path.match(/^(.*?campaigns\/([^\/]+)\/)/);
            let campName = "This Campaign";
            if (campaignMatch && campaignMatch[2]) {
                campName = decodeURIComponent(campaignMatch[2]);
            }
            renderedHtml = `<div style="text-align:center; margin-top:20%">
                                <h1>Welcome to ${campName}</h1>
                                <p style="color:#666">Select an entry from the sidebar to begin.</p>
                            </div>`;
        } else {
            // Parse and render the Markdown content normally using GFM for checkboxes
            renderedHtml = marked.parse(rawContent, { gfm: true, breaks: true });
        }
        
        if (isSessionPage && !isIndexJson) {
            // Append graphs if reading a session summary
            const graphsResponse = await fetch(path.replace('summary.md', 'graphs.md').replace('transcript.json', 'graphs.md').replace('transcript_annotated.json', 'graphs.md').replace('session_info.json', 'graphs.md').replace('transcript_diarized.json', 'graphs.md'));
            if (graphsResponse.ok) {
                const graphsMarkdown = await graphsResponse.text();
                // strip out the title "Session X - Graphs" since we already have it
                const strippedGraphs = graphsMarkdown.replace(/^# .*graphs\s*$/mi, '');
                renderedHtml += "\n<hr>\n" + marked.parse(strippedGraphs, { gfm: true, breaks: true });
            }
            
            // Check for recap.mp3
            const recapResponse = await fetch(path.replace('summary.md', 'recap.mp3'));
            let audioPlayerHtml = '';
            if (recapResponse.ok) {
                audioPlayerHtml = `
                    <div class="audio-player-container">
                        <h3>Session Recap (Highlights)</h3>
                        <audio class="audio-player" controls>
                            <source src="${path.replace('summary.md', 'recap.mp3')}" type="audio/mpeg">
                            Your browser does not support the audio element.
                        </audio>
                    </div>
                `;
            }
            
            // Check for session_info.json for metadata
            let metaHtml = '';
            let headerHtml = '';
            try {
                const infoResponse = await fetch(path.replace('summary.md', 'session_info.json'));
                if (infoResponse.ok) {
                    const infoJson = await infoResponse.json();
                    
                    const durationStr = infoJson.audio_duration ? 
                        `<span>⏱️ ${Math.floor(infoJson.audio_duration / 3600)}h ${Math.floor((infoJson.audio_duration % 3600) / 60)}m</span>` : '';
                        
                    const mediaLink = infoJson.media_url ? 
                        `<a href="${infoJson.media_url}" target="_blank" class="media-link">🎥 View Original Recording</a>` : '';
                        
                    if (durationStr || mediaLink) {
                        metaHtml = `
                            <div class="meta-info">
                                ${durationStr}
                                ${mediaLink}
                            </div>
                        `;
                    }
                }
            } catch(e) {}
            
            contentDiv.innerHTML = `
                <div class="session-header">
                    ${metaHtml}
                    ${audioPlayerHtml}
                </div>
                ${renderedHtml}
            `;
        } else {
            contentDiv.innerHTML = renderedHtml;
        }
        
        // Fix relative image paths to be relative to the markdown file's directory
        const images = contentDiv.querySelectorAll('img');
        const currentDir = path.substring(0, path.lastIndexOf('/'));
        images.forEach(img => {
            const src = img.getAttribute('src');
            if (src && !src.startsWith('http') && !src.startsWith('/')) {
                img.src = currentDir + '/' + src;
            }
        });

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
                        const parts = currentDir.split('/').filter(p => p !== '');
                        const hrefParts = href.split('/');
                        for (const part of hrefParts) {
                            if (part === '' || part === '.') continue;
                            if (part === '..') {
                                if (parts.length > 0 && parts[parts.length - 1] !== '..') {
                                    parts.pop();
                                } else {
                                    parts.push('..');
                                }
                            } else {
                                parts.push(part);
                            }
                        }
                        resolvedPath = parts.join('/');
                        if (currentDir.startsWith('/') && !resolvedPath.startsWith('/')) {
                            resolvedPath = '/' + resolvedPath;
                        }
                    }

                    // Are we clicking a link that leads back to a session summary or graph?
                    const isTargetSession = resolvedPath.includes('/sessions/') && (resolvedPath.endsWith('summary.md') || resolvedPath.endsWith('graphs.md'));
                    const targetPage = isTargetSession ? 'session.html' : 'index.html';

                    // Use history.pushState to navigate without a full page reload if we are on the correct viewer type, 
                    // else navigate normally to swap viewer modes.
                    const currentIsSessionViewer = window.location.pathname.endsWith('session.html');
                    if ((isTargetSession && currentIsSessionViewer) || (!isTargetSession && !currentIsSessionViewer)) {
                        const newUrl = new URL(window.location);
                        newUrl.searchParams.set('path', resolvedPath);
                        window.history.pushState({path: resolvedPath}, '', newUrl);
                        window.dispatchEvent(new Event('popstate'));
                    } else {
                        window.location.href = `${targetPage}?path=${resolvedPath}`;
                    }
                });
            }
        });
        
        if (isIndexJson) {
            // Document title for the index
            const campaignMatch = path.match(/^(.*?campaigns\/([^\/]+)\/)/);
            if (campaignMatch && campaignMatch[2]) {
                document.title = decodeURIComponent(campaignMatch[2]) + " - Bardic Aspiration";
            }
        } else {
            // Update the page title if a top-level heading exists
            const h1 = contentDiv.querySelector('h1');
            if (h1) {
                document.title = h1.textContent;
            }
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
                const links = Array.from(doc.querySelectorAll('a'));
                
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
                        
                        sessionsHtml += `<li><a href="session.html?path=${summaryPath}">Session ${parseInt(sessionId, 10)}${title !== `Session ${parseInt(sessionId, 10)}` ? `: ${title.split(': ')[1]}` : ''}</a></li>`;
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
                html += `<li><a href="index.html?path=${item.path}">${item.name}</a></li>`;
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

        // Intercept links in the sidebar to prevent full reload WHEN ON THE SAME VIEWER
        navContent.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', (e) => {
                const url = new URL(link.href);
                const isTargetSession = url.pathname.endsWith('session.html');
                const currentIsSessionViewer = window.location.pathname.endsWith('session.html');
                
                // If the link points to the same HTML file we are currently on, we can safely intercept!
                if ((isTargetSession && currentIsSessionViewer) || (!isTargetSession && !currentIsSessionViewer)) {
                    e.preventDefault();
                    const resolvedPath = url.searchParams.get('path');
                    window.history.pushState({path: resolvedPath}, '', url);
                    window.dispatchEvent(new Event('popstate'));
                }
                // Otherwise, let the browser load the link normally to switch between session.html <-> index.html
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
