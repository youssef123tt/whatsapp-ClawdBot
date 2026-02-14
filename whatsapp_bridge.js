/**
 * WhatsApp Bridge for whatsapp-web.js
 * Communicates with Python via stdin/stdout
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const readline = require('readline');

// Initialize WhatsApp client
const client = new Client({
    authStrategy: new LocalAuth({
        dataPath: './session'
    }),
    puppeteer: {
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

// QR Code generation for authentication
client.on('qr', (qr) => {
    console.error('QR Code received. Scan with WhatsApp:');
    qrcode.generate(qr, { small: true });
});

// Ready event
client.on('ready', () => {
    console.log('READY');
});

// Authentication events
client.on('authenticated', () => {
    console.error('WhatsApp authenticated');
});

client.on('auth_failure', (msg) => {
    console.error('Authentication failed:', msg);
});

// Message handler (for incoming messages and self-messages)
client.on('message_create', async (message) => {
    // You can emit this to Python if you want to handle incoming messages
    const messageData = {
        event: 'message_received',
        data: {
            id: message.id._serialized,
            from: message.from,
            to: message.to,
            body: message.body,
            timestamp: message.timestamp,
            isGroup: message.isGroupMsg,
            author: message.author || null,
            fromMe: message.fromMe
        }
    };
    console.log(JSON.stringify(messageData));
});

// Command processor
const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: false
});

rl.on('line', async (line) => {
    let current_request_id = null;
    try {
        const request = JSON.parse(line);
        current_request_id = request.request_id;
        const { command, params, request_id } = request;

        let response = { success: true, request_id, data: {} };

        switch (command) {
            case 'get_messages':
                response.data = await getMessages(params);
                break;

            case 'send_message':
                response.data = await sendMessage(params);
                break;

            case 'get_chats':
                response.data = await getChats(params);
                break;

            case 'search_messages':
                response.data = await searchMessages(params);
                break;

            case 'get_contact':
                response.data = await getContact(params);
                break;

            default:
                response = { success: false, request_id, error: `Unknown command: ${command}` };
        }

        console.log(JSON.stringify(response));
    } catch (error) {
        const errorMessage = error.message || error.toString() || "Unknown error";
        console.log(JSON.stringify({
            success: false,
            request_id: current_request_id,
            error: errorMessage,
            error_obj: JSON.stringify(error, Object.getOwnPropertyNames(error))
        }));
    }
});

// Command implementations
async function getMessages(params) {
    const { chat_id, limit = 50, start_date, end_date } = params;

    const chat = await client.getChatById(chat_id);
    const messages = await chat.fetchMessages({ limit });

    let filteredMessages = messages;

    // Filter by date if provided
    if (start_date || end_date) {
        const startTime = start_date ? new Date(start_date).getTime() / 1000 : 0;
        const endTime = end_date ? new Date(end_date).getTime() / 1000 : Infinity;

        filteredMessages = messages.filter(msg => {
            return msg.timestamp >= startTime && msg.timestamp <= endTime;
        });
    }

    return {
        messages: filteredMessages.map(msg => ({
            id: msg.id._serialized,
            from: msg.from,
            chat_id: msg.id.remote,
            body: msg.body,
            timestamp: new Date(msg.timestamp * 1000).toISOString(),
            type: msg.type,
            is_group: msg.isGroupMsg,
            author: msg.author || null
        }))
    };
}

async function sendMessage(params) {
    const { phone_number, message, reply_to } = params;

    // Format phone number for WhatsApp
    const chatId = phone_number.includes('@')
        ? phone_number
        : `${phone_number.replace(/[^0-9]/g, '')}@c.us`;

    let options = {};
    if (reply_to) {
        const msg = await client.getMessageById(reply_to);
        options.quotedMessageId = msg.id._serialized;
    }

    const sentMessage = await client.sendMessage(chatId, message, options);

    return {
        id: sentMessage.id._serialized,
        from: sentMessage.from,
        chat_id: sentMessage.id.remote,
        timestamp: new Date(sentMessage.timestamp * 1000).toISOString()
    };
}

async function getChats(params) {
    const { limit = 20 } = params;

    const chats = await client.getChats();
    const limitedChats = chats.slice(0, limit);

    return {
        chats: limitedChats.map(chat => ({
            id: chat.id._serialized,
            name: chat.name,
            is_group: chat.isGroup,
            last_message_time: chat.lastMessage
                ? new Date(chat.lastMessage.timestamp * 1000).toISOString()
                : null,
            unread_count: chat.unreadCount
        }))
    };
}

async function searchMessages(params) {
    const { query, chat_id, limit = 10 } = params;

    let chatsToSearch = [];

    if (chat_id) {
        const chat = await client.getChatById(chat_id);
        chatsToSearch = [chat];
    } else {
        chatsToSearch = await client.getChats();
    }

    const results = [];

    for (const chat of chatsToSearch) {
        if (results.length >= limit) break;

        const messages = await chat.fetchMessages({ limit: 100 });

        for (const msg of messages) {
            if (results.length >= limit) break;

            if (msg.body && msg.body.toLowerCase().includes(query.toLowerCase())) {
                results.push({
                    id: msg.id._serialized,
                    chat_id: msg.id.remote,
                    from: msg.from,
                    body: msg.body,
                    timestamp: new Date(msg.timestamp * 1000).toISOString()
                });
            }
        }
    }

    return { messages: results };
}

async function getContact(params) {
    const { phone_number } = params;

    const contactId = phone_number.includes('@')
        ? phone_number
        : `${phone_number.replace(/[^0-9]/g, '')}@c.us`;

    const contact = await client.getContactById(contactId);

    return {
        name: contact.name || contact.pushname || phone_number,
        is_business: contact.isBusiness,
        status: contact.statusMuted ? 'muted' : 'active'
    };
}

// Initialize client
client.initialize();

// Handle process termination
process.on('SIGTERM', async () => {
    await client.destroy();
    process.exit(0);
});
