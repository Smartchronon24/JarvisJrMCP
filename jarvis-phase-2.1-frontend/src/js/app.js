/* filepath: c:\Navaneth\Study\JarvisMCP\jarvis-phase-2.1-frontend\src\js\app.js */
/**
 * Main Application Orchestrator
 * Coordinates pages, navigation, initialization
 */

class JarvisApp {
    constructor() {
        this.pages = {
            home: document.getElementById('page-home'),
            activity: document.getElementById('page-activity'),
            tools: document.getElementById('page-tools'),
            settings: document.getElementById('page-settings'),
        };

        this.navItems = document.querySelectorAll('.nav-item');
        this.init();
    }

    init() {
        this.setupNavigation();
        this.showPage('home');
    }

    setupNavigation() {
        this.navItems.forEach((item) => {
            item.addEventListener('click', () => {
                const page = item.dataset.page;
                this.showPage(page);
            });
        });

        // Settings button in footer
        document.querySelector('.settings-btn').addEventListener('click', () => {
            this.showPage('settings');
        });
    }

    showPage(pageName) {
        // Hide all pages
        Object.values(this.pages).forEach((page) => {
            page.classList.remove('active');
        });

        // Show selected page
        if (this.pages[pageName]) {
            this.pages[pageName].classList.add('active');
        }

        // Update active nav item
        this.navItems.forEach((item) => {
            if (item.dataset.page === pageName) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        appState.setCurrentPage(pageName);
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const app = new JarvisApp();
});