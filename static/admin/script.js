/** StoryBot Admin Panel JavaScript */

// State
let stories = [];
let assigningStoryId = null;
let nfcEventSource = null;

// Hardware status elements
const nfcStatusIcon = document.getElementById('nfc-status');
const ledStatusIcon = document.getElementById('led-status');

// Polling interval (5 seconds)
const STATUS_POLL_INTERVAL = 5000;
let statusPollId = null;

// DOM Elements
const uploadForm = document.getElementById('upload-form');
const storyListContainer = document.getElementById('story-list');
const statusMessage = document.getElementById('status-message');

/**
 * Show status message to user
 * @param {string} text - Message text
 * @param {string} type - Message type: 'success', 'error', 'info'
 */
function showMessage(text, type = 'info') {
    statusMessage.textContent = text;
    statusMessage.className = `status-message ${type}`;
    statusMessage.classList.remove('hidden');

    // Auto-hide after 5 seconds for success/error, keep info messages
    if (type !== 'info') {
        setTimeout(() => {
            statusMessage.classList.add('hidden');
        }, 5000);
    }
}

/**
 * Hide status message
 */
function hideMessage() {
    statusMessage.classList.add('hidden');
}

/**
 * Load all stories from API
 */
async function loadStories() {
    try {
        const response = await fetch('/api/stories');
        if (!response.ok) {
            throw new Error(`Failed to load stories: ${response.status}`);
        }
        const data = await response.json();
        stories = data.stories || [];
        renderStoryList();
    } catch (error) {
        console.error('Error loading stories:', error);
        showMessage('Failed to load stories. Please refresh the page.', 'error');
    }
}

/**
 * Render story list to DOM
 */
function renderStoryList() {
    if (stories.length === 0) {
        storyListContainer.innerHTML = '<p class="empty-state">No stories yet. Upload your first story above!</p>';
        return;
    }

    storyListContainer.innerHTML = '';
    stories.forEach(story => {
        const card = createStoryCard(story);
        storyListContainer.appendChild(card);
    });
}

/**
 * Create a story card element
 * @param {Object} story - Story object
 * @returns {HTMLElement} Story card element
 */
function createStoryCard(story) {
    const card = document.createElement('div');
    card.className = 'story-card';
    card.dataset.storyId = story.id;

    const emoji = document.createElement('div');
    emoji.className = 'story-emoji';
    emoji.textContent = story.emoji || '📖';

    const info = document.createElement('div');
    info.className = 'story-info';

    const title = document.createElement('h3');
    title.className = 'story-title';
    title.textContent = story.title;

    const nfcStatus = document.createElement('p');
    nfcStatus.className = 'story-nfc-status';
    if (story.nfc_uid) {
        nfcStatus.textContent = `NFC: ${story.nfc_uid}`;
        nfcStatus.classList.add('assigned');
    } else {
        nfcStatus.textContent = 'No NFC card assigned';
    }

    info.appendChild(title);
    info.appendChild(nfcStatus);

    const actions = document.createElement('div');
    actions.className = 'story-actions';

    // Assign/Unassign NFC button
    const nfcButton = document.createElement('button');
    nfcButton.className = story.nfc_uid ? 'btn btn-success' : 'btn btn-warning';
    nfcButton.textContent = story.nfc_uid ? 'Reassign NFC' : 'Assign NFC';
    nfcButton.onclick = () => startNFCAssignment(story.id);
    actions.appendChild(nfcButton);

    // Delete button
    const deleteButton = document.createElement('button');
    deleteButton.className = 'btn btn-danger';
    deleteButton.textContent = 'Delete';
    deleteButton.onclick = () => deleteStory(story.id, story.title);
    actions.appendChild(deleteButton);

    card.appendChild(emoji);
    card.appendChild(info);
    card.appendChild(actions);

    return card;
}

/**
 * Upload a new story
 * @param {Event} event - Form submit event
 */
async function uploadStory(event) {
    event.preventDefault();

    const formData = new FormData(uploadForm);
    const submitButton = uploadForm.querySelector('button[type="submit"]');

    try {
        // Disable button and show loading
        submitButton.disabled = true;
        submitButton.textContent = 'Uploading...';
        hideMessage();

        const response = await fetch('/api/stories', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to upload story');
        }

        const story = await response.json();
        showMessage(`Story "${story.title}" uploaded successfully!`, 'success');

        // Reset form and reload list
        uploadForm.reset();
        await loadStories();

    } catch (error) {
        console.error('Error uploading story:', error);
        showMessage(error.message || 'Failed to upload story', 'error');
    } finally {
        // Re-enable button
        submitButton.disabled = false;
        submitButton.textContent = 'Upload Story';
    }
}

/**
 * Delete a story
 * @param {string} storyId - Story ID to delete
 * @param {string} storyTitle - Story title for confirmation
 */
async function deleteStory(storyId, storyTitle) {
    if (!confirm(`Are you sure you want to delete "${storyTitle}"?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/stories/${storyId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error(`Failed to delete story: ${response.status}`);
        }

        showMessage(`Story "${storyTitle}" deleted`, 'success');
        await loadStories();

    } catch (error) {
        console.error('Error deleting story:', error);
        showMessage('Failed to delete story', 'error');
    }
}

/**
 * Start NFC assignment flow
 * @param {string} storyId - Story ID to assign NFC card to
 */
function startNFCAssignment(storyId) {
    // Close any existing connection
    if (nfcEventSource) {
        nfcEventSource.close();
    }

    assigningStoryId = storyId;
    showMessage('Tap NFC card to assign...', 'info');

    // Open SSE connection
    nfcEventSource = new EventSource('/api/nfc/read');

    nfcEventSource.addEventListener('card', (event) => {
        try {
            const { uid } = JSON.parse(event.data);
            handleNFCTap(uid);
        } catch (error) {
            console.error('Error parsing NFC event:', error);
        }
    });

    nfcEventSource.addEventListener('error', (error) => {
        console.error('NFC connection error:', error);
        showMessage('NFC connection error. Please try again.', 'error');
        closeNFCConnection();
    });

    nfcEventSource.onerror = () => {
        showMessage('NFC connection error. Please try again.', 'error');
        closeNFCConnection();
    };
}

/**
 * Handle NFC card tap
 * @param {string} uid - NFC card UID
 */
async function handleNFCTap(uid) {
    if (!assigningStoryId) {
        return;
    }

    try {
        const response = await fetch(`/api/stories/${assigningStoryId}/nfc`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ nfc_uid: uid })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to assign NFC card');
        }

        const story = await response.json();
        showMessage(`NFC card assigned to "${story.title}"`, 'success');
        closeNFCConnection();
        await loadStories();

    } catch (error) {
        console.error('Error assigning NFC:', error);
        showMessage(error.message || 'Failed to assign NFC card', 'error');
        closeNFCConnection();
    }
}

/**
 * Close NFC SSE connection
 */
function closeNFCConnection() {
    if (nfcEventSource) {
        nfcEventSource.close();
        nfcEventSource = null;
    }
    assigningStoryId = null;
}

/**
 * Update hardware status icons based on API response
 */
async function updateHardwareStatus() {
    try {
        const response = await fetch('/api/system/status');
        if (!response.ok) throw new Error('Status fetch failed');

        const data = await response.json();

        // Update NFC status
        updateStatusIcon(
            nfcStatusIcon,
            data.hardware?.nfc,
            'NFC Reader'
        );

        // Update LED status
        updateStatusIcon(
            ledStatusIcon,
            data.hardware?.led,
            'LED Strip'
        );
    } catch (error) {
        console.error('Failed to fetch hardware status:', error);
        // Mark both as unknown/error
        if (nfcStatusIcon) {
            nfcStatusIcon.className = 'status-icon disconnected';
            nfcStatusIcon.title = 'NFC Reader: Connection error';
        }
        if (ledStatusIcon) {
            ledStatusIcon.className = 'status-icon disconnected';
            ledStatusIcon.title = 'LED Strip: Connection error';
        }
    }
}

/**
 * Update a single status icon
 * @param {HTMLElement} icon - The icon element
 * @param {Object} hwState - Hardware state object from API
 * @param {string} label - Human-readable label
 */
function updateStatusIcon(icon, hwState, label) {
    if (!icon) return;

    let statusClass = 'status-icon';
    let statusText = 'Unknown';

    if (!hwState) {
        statusClass += ' disconnected';
        statusText = 'Not available';
    } else if (hwState.status === 'ok') {
        statusClass += ' connected';
        statusText = hwState.is_mock ? 'Connected (simulated)' : 'Connected';
        if (hwState.is_mock) {
            statusClass += ' mock';
        }
    } else if (hwState.status === 'error') {
        statusClass += ' disconnected';
        statusText = hwState.error_message || 'Error';
    } else {
        statusClass += ' disconnected';
        statusText = 'Not connected';
    }

    icon.className = statusClass;
    icon.title = `${label}: ${statusText}`;
}

/**
 * Start polling for hardware status
 */
function startStatusPolling() {
    // Set initial checking state
    if (nfcStatusIcon) nfcStatusIcon.className = 'status-icon checking';
    if (ledStatusIcon) ledStatusIcon.className = 'status-icon checking';

    // Initial fetch
    updateHardwareStatus();

    // Start polling
    statusPollId = setInterval(updateHardwareStatus, STATUS_POLL_INTERVAL);
}

/**
 * Stop polling (for cleanup)
 */
function stopStatusPolling() {
    if (statusPollId) {
        clearInterval(statusPollId);
        statusPollId = null;
    }
}

/**
 * Clean up on page unload
 */
function cleanup() {
    closeNFCConnection();
    stopStatusPolling();  // NEW: Stop polling on page unload
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    loadStories();
    uploadForm.addEventListener('submit', uploadStory);
    startStatusPolling();  // NEW: Start hardware status polling
});

window.addEventListener('beforeunload', cleanup);
