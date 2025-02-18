document.addEventListener("DOMContentLoaded", function() {  
    console.log("Socket.IO client script loaded");  
    let socket = io();  
  
    socket.on('connect', function() {  
        console.log("Connected to server");  

        setInterval(function() {
            socket.emit('ping');
            console.log("Ping sent to server");
        }, 30000);
    });  

    let previousContent = '';  
    let updateTimeout = null;  

    function updateContent(content, lang) {  
        if (content === previousContent) {  
            return;  
        }  
        previousContent = content;  
  
        let contentDiv = document.getElementById('content');  
  
        contentDiv.innerHTML = content; 

        contentDiv.classList.remove('zh', 'en');  
        if (lang === 'zh-TW' || lang === 'zh') {  
            contentDiv.classList.add('en');  
        } else if (lang === 'en-US' || lang === 'en') {  
            contentDiv.classList.add('zh');  
        }

        if (contentDiv.scrollHeight > contentDiv.clientHeight) {  
            contentDiv.scrollTop = contentDiv.scrollHeight;  
        }  
    }  

    function debounce(func, wait) {  
        return function(...args) {  
            if (updateTimeout) {  
                clearTimeout(updateTimeout);  
            }  
            updateTimeout = setTimeout(() => {  
                func.apply(this, args);  
            }, wait);  
        };  
    }  

    const debouncedUpdateContent = debounce(updateContent, 100);  
  
    socket.on('update_text', function(msg) {  
        console.log("Received translated text:", msg.text);  
        let content = msg.text;  
        let lang = msg.lang;  
  
        debouncedUpdateContent(content, lang);  
    });  
  
    socket.on('disconnect', function() {  
        console.error('Disconnected from server!');  
    });  

    socket.on('pong', function() {
        console.log("Received pong from server");
    });
});  