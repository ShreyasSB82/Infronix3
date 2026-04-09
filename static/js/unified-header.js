
(function() {
    const header = document.createElement('header');
    header.className = 'infronix-unified-header';
    
    const pathname = window.location.pathname;
    
    header.innerHTML = `
        <a href="/" class="infronix-logo">INFRONIX</a>
        <div class="infronix-tagline">"from city vision → into real infrastructure intelligence."</div>
        <nav class="infronix-nav">
            <a href="/plot-details" class="infronix-nav-link ${pathname === '/plot-details' ? 'active' : ''}">PLOT DETAILS</a>
            <a href="/interior-layout" class="infronix-nav-link ${pathname === '/interior-layout' ? 'active' : ''}">PLANNER</a>
            <a href="/viewer" class="infronix-nav-link ${pathname === '/viewer' ? 'active' : ''}">3D VIEWER</a>
        </nav>
    `;
    
    document.body.prepend(header);
})();
