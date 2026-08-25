/* filepath: c:\Navaneth\Study\JarvisMCP\frontend\src\js\mock-data.js */
/**
 * Mock Data Layer
 * Provides realistic demo data without backend integration
 */

const mockMessages = [
    {
        id: 1,
        role: 'user',
        content: 'Find the cheapest RTX 5070 available in India.',
        timestamp: new Date(Date.now() - 300000),
    },
    {
        id: 2,
        role: 'assistant',
        content: 'I\'ll search for RTX 5070 prices across major retailers in India and compare them for you.',
        timestamp: new Date(Date.now() - 290000),
    },
];

const mockToolExecutions = [
    {
        id: 'exec-1',
        mcpServer: 'tavily',
        tool: 'search',
        status: 'completed',
        startTime: new Date(Date.now() - 280000),
        duration: 1420,
        arguments: {
            query: 'RTX 5070 price India',
        },
        result: '5 relevant sources found with current pricing information',
    },
    {
        id: 'exec-2',
        mcpServer: 'firecrawl',
        tool: 'scrape',
        status: 'completed',
        startTime: new Date(Date.now() - 200000),
        duration: 2180,
        arguments: {
            url: 'amazon.in/RTX-5070',
        },
        result: 'Successfully scraped product details',
    },
];

const mockMcpServers = [
    {
        id: 'memory',
        name: 'Memory',
        description: 'Personal memory and context management',
        icon: '🧠',
        connected: true,
        tools: ['create_entities', 'recall', 'forget', 'list_memories'],
    },
    {
        id: 'filesystem',
        name: 'Filesystem',
        description: 'Local file operations',
        icon: '📁',
        connected: true,
        tools: ['read_file', 'write_file', 'list_directory', 'delete_file'],
    },
    {
        id: 'playwright',
        name: 'Playwright',
        description: 'Visible browser automation',
        icon: '🌐',
        connected: true,
        tools: ['navigate', 'click', 'type', 'screenshot'],
    },
    {
        id: 'exa',
        name: 'Exa',
        description: 'Web research and news',
        icon: '🔍',
        connected: true,
        tools: ['search', 'find_similar', 'get_content'],
    },
    {
        id: 'tavily',
        name: 'Tavily',
        description: 'Web search and extraction',
        icon: '🔎',
        connected: true,
        tools: ['search', 'extract'],
    },
    {
        id: 'firecrawl',
        name: 'Firecrawl',
        description: 'Web scraping and crawling',
        icon: '🔗',
        connected: true,
        tools: ['scrape', 'crawl'],
    },
    {
        id: 'whatsapp',
        name: 'WhatsApp',
        description: 'Messaging integration',
        icon: '💬',
        connected: true,
        tools: ['send_message', 'read_messages'],
    },
];

const mockSettings = {
    general: {
        jarvisName: 'Jarvis',
        startupBehavior: 'home',
        density: 'comfortable',
    },
    appearance: {
        theme: 'dark',
        accentColor: '#8b5cf6',
        animations: true,
    },
    mcp: {
        memory: true,
        filesystem: true,
        playwright: true,
        exa: true,
        tavily: true,
        firecrawl: true,
        whatsapp: true,
    },
};