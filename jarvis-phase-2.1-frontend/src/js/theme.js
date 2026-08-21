/* filepath: c:\Navaneth\Study\JarvisMCP\jarvis-phase-2.1-frontend\src\js\theme.js */
/**
 * Theme Management
 * Handles dark/light themes and color persistence
 */

class ThemeManager {
    constructor() {
        this.currentTheme = this.loadTheme();
        this.accentColor = this.loadAccentColor();
        this.init();
    }

    init() {
        this.applyTheme(this.currentTheme);
        this.applyAccentColor(this.accentColor);
        this.setupThemeListeners();
    }

    loadTheme() {
        const stored = localStorage.getItem('jarvis_appearance_theme');
        if (stored) {
            return stored;
        }
        return 'dark';
    }

    loadAccentColor() {
        const stored = localStorage.getItem('jarvis_appearance_accentColor');
        if (stored) {
            return stored;
        }
        return '#8b5cf6';
    }

    applyTheme(theme) {
        if (theme === 'system') {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            theme = prefersDark ? 'dark' : 'light';
        }
        document.documentElement.setAttribute('data-theme', theme);
        this.currentTheme = theme;
        localStorage.setItem('jarvis_appearance_theme', theme);
    }

    applyAccentColor(color) {
        document.documentElement.style.setProperty('--accent', color);
        document.documentElement.style.setProperty(
            '--accent-hover',
            this.lightenColor(color, 0.2)
        );
        document.documentElement.style.setProperty(
            '--accent-active',
            this.darkenColor(color, 0.2)
        );
        this.accentColor = color;
        localStorage.setItem('jarvis_appearance_accentColor', color);
    }

    lightenColor(color, factor) {
        const c = color.substring(1);
        const rgb = parseInt(c, 16);
        const r = Math.min(255, (rgb >> 16) + Math.round(255 * factor));
        const g = Math.min(255, ((rgb >> 8) & 0xff) + Math.round(255 * factor));
        const b = Math.min(255, (rgb & 0xff) + Math.round(255 * factor));
        return '#' + ((r << 16) | (g << 8) | b).toString(16).padStart(6, '0');
    }

    darkenColor(color, factor) {
        const c = color.substring(1);
        const rgb = parseInt(c, 16);
        const r = Math.max(0, (rgb >> 16) - Math.round(255 * factor));
        const g = Math.max(0, ((rgb >> 8) & 0xff) - Math.round(255 * factor));
        const b = Math.max(0, (rgb & 0xff) - Math.round(255 * factor));
        return '#' + ((r << 16) | (g << 8) | b).toString(16).padStart(6, '0');
    }

    setupThemeListeners() {
        window.matchMedia('(prefers-color-scheme: dark)').addListener(() => {
            if (appState.getSetting('appearance', 'theme') === 'system') {
                this.applyTheme('system');
            }
        });
    }

    getTheme() {
        return this.currentTheme;
    }

    getAccentColor() {
        return this.accentColor;
    }
}

const themeManager = new ThemeManager();