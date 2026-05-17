// static/signup_validation.js

document.addEventListener('DOMContentLoaded', function() {
    // Get the password input field and the message display area using their IDs
    const passwordInput = document.getElementById('password_input');
    const messageElement = document.getElementById('password_message');

    // Function to send the password to Flask for validation
    function validatePasswordDynamically() {
        const password = passwordInput.value;
        
        // Clear message if field is empty
        if (password.length === 0) {
            messageElement.textContent = '';
            return;
        }

        const data = { 'password': password };

        // Fetch API to send data to the Flask route via AJAX
        fetch('/validate_password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data),
        })
        .then(response => response.json()) // Parse the JSON response
        .then(result => {
            // Update the message text
            messageElement.textContent = result.message;
            
            // Apply color based on validity
            if (result.valid) {
                messageElement.style.color = 'green';
            } else {
                messageElement.style.color = 'red';
            }
        })
        .catch(error => {
            console.error('Error during dynamic password validation:', error);
            messageElement.textContent = 'Validation check failed.';
            messageElement.style.color = 'orange';
        });
    }

    // Attach the function to the 'input' event (fires on every key stroke)
    passwordInput.addEventListener('input', validatePasswordDynamically);
});