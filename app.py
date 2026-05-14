from flask import Flask, render_template_string, request, jsonify
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
import os

load_dotenv()

app = Flask(__name__)

# Configuration de la base de données
DB_CONFIG = {
    "dbname": "ma_base_vector",
    "user": "postgres",
    "password": "Yacine-96",
    "host": "localhost",
    "port": "5433"
}


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BNM Chat - Historique des conversations</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
        }

        body {
            background: #f0f2f5;
            height: 100vh;
            width: 100vw;
            margin: 0;
            padding: 0;
            overflow: hidden;
        }

        .container {
            width: 100vw;
            height: 100vh;
            background: white;
            display: flex;
            overflow: hidden;
        }

        /* Sidebar avec avatars */
        .sidebar {
            width: 350px;
            background: white;
            border-right: 1px solid #e0e0e0;
            display: flex;
            flex-direction: column;
            height: 100%;
        }

        .sidebar-header {
            padding: 20px;
            background: #007bff;
            color: white;
        }

        .sidebar-header h2 {
            font-size: 1.3rem;
            font-weight: 600;
            margin-bottom: 5px;
        }

        .sidebar-header p {
            font-size: 0.9rem;
            opacity: 0.9;
        }

        .users-list {
            flex: 1;
            overflow-y: auto;
        }

        .user-item {
            padding: 12px 20px;
            border-bottom: 1px solid #f0f0f0;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 12px;
            transition: background 0.2s;
        }

        .user-item:hover {
            background: #f8f9fa;
        }

        .user-item.active {
            background: #e3f2fd;
        }

        .user-avatar {
            width: 36px;
            height: 36px;
            background: #007bff;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            font-size: 1rem;
            flex-shrink: 0;
        }

        .user-item.active .user-avatar {
            background: white;
            color: #007bff;
            border: 2px solid #007bff;
        }

        .user-content {
            flex: 1;
        }

        .user-name {
            font-weight: 600;
            font-size: 0.95rem;
            margin-bottom: 3px;
            color: #000;
        }

        .user-preview {
            font-size: 0.9rem;
            color: #666;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 170px;
        }

        .user-date {
            font-size: 0.7rem;
            color: #999;
            margin-left: 10px;
            white-space: nowrap;
        }

        /* Panneau principal */
        .main-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: white;
        }

        .chat-header {
            padding: 15px 20px;
            border-bottom: 1px solid #e9ecef;
            background: #f8f9fa;
        }

        .chat-header .user-avatar {
            width: 45px;
            height: 45px;
            background: #007bff;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            font-size: 1.3rem;
        }

        .chat-header h3 {
            color: #333;
            font-size: 1.2rem;
            margin-bottom: 5px;
        }

        .chat-header p {
            color: #6c757d;
            font-size: 0.9rem;
        }

        .messages-container {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            background: #f5f7fb;
        }

        .message-date {
            text-align: center;
            margin: 20px 0;
            color: #6c757d;
            font-size: 0.8rem;
            font-weight: 500;
        }

        .message {
            display: flex;
            margin-bottom: 15px;
        }

        .message.user {
            justify-content: flex-end;
        }

        .message-content {
            max-width: 70%;
            padding: 12px 16px;
            border-radius: 18px;
            position: relative;
        }

        .message.user .message-content {
            background: #007bff;
            color: white;
            border-bottom-right-radius: 4px;
        }

        .message.assistant .message-content {
            background: white;
            color: #333;
            border-bottom-left-radius: 4px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }

        .message-time {
            font-size: 0.7rem;
            margin-top: 5px;
            opacity: 0.7;
        }

        .session-badge {
            background: #e9ecef;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.7rem;
            color: #495057;
            display: inline-block;
            margin-top: 5px;
        }

        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #adb5bd;
            text-align: center;
            padding: 20px;
        }

        .empty-state h3 {
            margin-bottom: 10px;
            color: #6c757d;
        }

        .loading {
            text-align: center;
            padding: 20px;
            color: #6c757d;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Sidebar avec avatars -->
        <div class="sidebar">
            <div class="sidebar-header">
                <h2>Conversations BNM</h2>
                <p>{{ users|length }} utilisateur(s)</p>
            </div>
            <div class="users-list" id="usersList">
                {% for user in users %}
                <div class="user-item" onclick="loadUserHistory('{{ user.username }}')" id="user-{{ user.username|replace(' ', '_') }}">
                    <div class="user-avatar">
                        {{ user.username[0]|upper }}
                    </div>
                    <div class="user-content">
                        <div class="user-name">{{ user.username }}</div>
                        <div class="user-preview">{{ user.last_message[:50] + '...' if user.last_message and user.last_message|length > 50 else user.last_message }}</div>
                    </div>
                    <div class="user-date">{{ user.last_time.strftime('%d/%m') if user.last_time else '' }}</div>
                </div>
                {% endfor %}
            </div>
        </div>

        <!-- Panneau principal avec en-tête amélioré -->
        <div class="main-panel" id="mainPanel">
            <div class="chat-header" id="chatHeader">
                <div style="display: flex; align-items: center; gap: 15px;">
                    <div class="user-avatar" id="headerAvatar">?</div>
                    <div>
                        <h3 id="selectedUserName">Sélectionnez un utilisateur</h3>
                        <p id="selectedUserInfo">Cliquez sur un nom pour voir son historique</p>
                    </div>
                </div>
            </div>
            <div class="messages-container" id="messagesContainer">
                <div class="empty-state">
                    <h3> Sélectionnez un utilisateur</h3>
                    <p>Choisissez un nom dans la liste pour voir son historique de conversation</p>
                </div>
            </div>
        </div>
    </div>

    <script>
        function updateChatHeader(username, avatar) {
            document.getElementById('headerAvatar').textContent = avatar;
            document.getElementById('selectedUserName').textContent = username;
        }

        async function loadUserHistory(username) {
            document.querySelectorAll('.user-item').forEach(el => {
                el.classList.remove('active');
            });

            const userId = `user-${username.replace(/ /g, '_')}`;
            document.getElementById(userId).classList.add('active');

            // Mettre à jour l'en-tête avec l'avatar
            updateChatHeader(username, username[0].toUpperCase());

            document.getElementById('selectedUserInfo').textContent = 'Chargement...';

            document.getElementById('messagesContainer').innerHTML = `
                <div class="loading">
                    <p>Chargement des messages...</p>
                </div>
            `;

            try {
                const response = await fetch(`/api/user/${encodeURIComponent(username)}/history`);
                const data = await response.json();

                if (data.success) {
                    displayMessages(data.messages, username);
                    const lastDate = new Date(data.last_active).toLocaleString('fr-FR');
                    document.getElementById('selectedUserInfo').textContent = 
                        `${data.messages.length} message(s) - Dernier: ${lastDate}`;
                } else {
                    throw new Error(data.error);
                }
            } catch (error) {
                document.getElementById('messagesContainer').innerHTML = `
                    <div class="empty-state">
                        <h3> Erreur</h3>
                        <p>Impossible de charger les messages</p>
                    </div>
                `;
            }
        }

        function displayMessages(messages, username) {
            if (!messages || messages.length === 0) {
                document.getElementById('messagesContainer').innerHTML = `
                    <div class="empty-state">
                        <h3>💬 Aucun message</h3>
                        <p>Cet utilisateur n'a pas encore de conversation</p>
                    </div>
                `;
                return;
            }

            let html = '';
            let currentDate = '';

            messages.forEach(msg => {
                const msgDate = new Date(msg.timestamp).toLocaleDateString('fr-FR', {
                    weekday: 'long',
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric'
                });

                if (msgDate !== currentDate) {
                    html += `<div class="message-date">${msgDate}</div>`;
                    currentDate = msgDate;
                }

                const timeStr = new Date(msg.timestamp).toLocaleTimeString('fr-FR', {
                    hour: '2-digit',
                    minute: '2-digit'
                });

                html += `
                    <div class="message ${msg.role}">
                        <div class="message-content">
                            <div>${msg.content.replace(/\\n/g, '<br>')}</div>
                            <div class="message-time">${timeStr}</div>
                            <div class="session-badge">Session: ${msg.session_id.slice(0,8)}...</div>
                        </div>
                    </div>
                `;
            });

            document.getElementById('messagesContainer').innerHTML = html;
            document.getElementById('messagesContainer').scrollTop = 0;
        }
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()

    # Récupérer tous les utilisateurs avec leur dernier message
    cur.execute("""
        SELECT DISTINCT ON (u.username)
            u.username,
            u.email,
            ch.content as last_message,
            ch.timestamp as last_time
        FROM users u
        LEFT JOIN conversation_history ch ON u.user_id = ch.user_id
        ORDER BY u.username, ch.timestamp DESC;
    """)

    users = []
    for username, email, last_message, last_time in cur.fetchall():
        users.append({
            'username': username,
            'email': email,
            'last_message': last_message if last_message else "Aucun message",
            'last_time': last_time
        })

    cur.close()
    conn.close()

    return render_template_string(HTML_TEMPLATE, users=users)


@app.route('/api/user/<username>/history')
def user_history(username):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Vérifier si l'utilisateur existe
        cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
        user = cur.fetchone()

        if not user:
            return jsonify({
                'success': False,
                'error': f"Utilisateur '{username}' non trouvé"
            }), 404

        # Récupérer tout l'historique de l'utilisateur
        cur.execute("""
            SELECT 
                ch.role,
                ch.content,
                ch.timestamp,
                ch.session_id
            FROM conversation_history ch
            JOIN users u ON ch.user_id = u.user_id
            WHERE u.username = %s
            ORDER BY ch.timestamp ASC;
        """, (username,))

        messages = []
        for role, content, timestamp, session_id in cur.fetchall():
            messages.append({
                'role': role,
                'content': content,
                'timestamp': timestamp.isoformat(),
                'session_id': session_id
            })

        last_active = messages[-1]['timestamp'] if messages else None

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'messages': messages,
            'last_active': last_active,
            'count': len(messages)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    app.run(debug=True)