/** StoryBot Admin Panel JavaScript */

// State
let stories = [];
let assigningStoryId = null;
let nfcEventSource = null;

// Edit mode state
let formMode = 'upload'; // 'upload' | 'edit'
let editingStoryId = null;
let originalStoryData = null; // For dirty checking
let removeCoverFlag = false;

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
const cancelEditBtn = document.getElementById('cancel-edit');
const clearCoverBtn = document.getElementById('clear-cover');
const coverActionsDiv = document.getElementById('cover-actions');
const currentCoverName = document.getElementById('current-cover-name');

// Emoji Picker State
let emojiPickerOpen = false;
let activeCategory = 'Animals';

// Emoji Categories Data
const emojiCategories = {
    Animals: ['🐶', '🐱', '🐭', '🐰', '🦊', '🐻', '🐼', '🐨', '🐯', '🦁', '🐮', '🐷', '🐸', '🐵', '🐔', '🐧', '🐦', '🦆'],
    Food: ['🍎', '🍊', '🍋', '🍇', '🍓', '🫐', '🍑', '🍒', '🥕', '🥦', '🍞', '🥐', '🧀', '🍕', '🍰', '🍪', '🥛', '🍩'],
    Weather: ['☀️', '🌤️', '⛅', '🌧️', '❄️', '🌈', '☁️', '🌪️', '🔥', '🌊', '🌙', '⭐', '✨', '🌟', '🌈', '🌦️', '🌨️', '🌩️'],
    Activities: ['🎨', '🎭', '🎪', '🎰', '🎲', '🎯', '🎳', '🎵', '🎶', '🎤', '🏃', '🚴', '🏊', '🎪', '🎬', '🎮', '🎯', '🏆'],
    Emotions: ['😊', '😄', '😂', '🥰', '😢', '😠', '😴', '🤔', '😮', '🤗', '😇', '😎', '🥳', '🤩', '😌', '🥲', '😏', '😋'],
    Objects: ['🎁', '🎈', '🎀', '🎊', '🎉', '📚', '✏️', '🎓', '🏠', '🚗', '✈️', '🚀', '⏰', '💡', '🔔', '📷', '🎩', '🧸']
};

// Emoji Keywords for Search
const emojiKeywords = {
    '🐶': ['dog', 'puppy', 'pet'],
    '🐱': ['cat', 'kitten', 'pet'],
    '🐭': ['mouse', 'pet'],
    '🐰': ['rabbit', 'bunny', 'pet'],
    '🦊': ['fox'],
    '🐻': ['bear'],
    '🐼': ['panda'],
    '🐨': ['koala'],
    '🐯': ['tiger'],
    '🦁': ['lion'],
    '🐮': ['cow'],
    '🐷': ['pig'],
    '🐸': ['frog'],
    '🐵': ['monkey'],
    '🐔': ['chicken', 'hen'],
    '🐧': ['penguin'],
    '🐦': ['bird'],
    '🦆': ['duck'],
    '🍎': ['apple', 'fruit', 'red'],
    '🍊': ['orange', 'fruit'],
    '🍋': ['lemon', 'fruit'],
    '🍇': ['grape', 'fruit'],
    '🍓': ['strawberry', 'fruit'],
    '🫐': ['blueberry', 'fruit'],
    '🍑': ['peach', 'fruit'],
    '🍒': ['cherry', 'fruit'],
    '🥕': ['carrot', 'vegetable'],
    '🥦': ['broccoli', 'vegetable'],
    '🍞': ['bread'],
    '🥐': ['croissant'],
    '🧀': ['cheese'],
    '🍕': ['pizza'],
    '🍰': ['cake', 'dessert'],
    '🍪': ['cookie', 'dessert'],
    '🥛': ['milk', 'drink'],
    '🍩': ['donut', 'dessert'],
    '☀️': ['sun', 'sunny', 'day'],
    '🌤️': ['sun behind cloud'],
    '⛅': ['cloud', 'cloudy'],
    '🌧️': ['rain', 'rainy'],
    '❄️': ['snow', 'snowflake', 'cold'],
    '🌈': ['rainbow'],
    '☁️': ['cloud'],
    '🌪️': ['tornado', 'wind'],
    '🔥': ['fire', 'hot'],
    '🌊': ['wave', 'water', 'sea'],
    '🌙': ['moon', 'night'],
    '⭐': ['star'],
    '✨': ['sparkles', 'sparkle'],
    '🌟': ['glowing star'],
    '🌦️': ['sun rain'],
    '🌨️': ['snow cloud'],
    '🌩️': ['lightning', 'thunder'],
    '🎨': ['art', 'paint', 'palette'],
    '🎭': ['theater', 'mask', 'drama'],
    '🎪': ['circus', 'tent'],
    '🎰': ['slot machine'],
    '🎲': ['dice', 'game'],
    '🎯': ['target', 'bullseye'],
    '🎳': ['bowling'],
    '🎵': ['music note'],
    '🎶': ['music notes'],
    '🎤': ['microphone', 'sing'],
    '🏃': ['run', 'running', 'run'],
    '🚴': ['bicycle', 'bike'],
    '🏊': ['swim', 'swimming'],
    '🎬': ['movie', 'film', 'camera'],
    '🎮': ['game', 'video game'],
    '🏆': ['trophy', 'winner'],
    '😊': ['smile', 'happy'],
    '😄': ['laugh', 'laughing', 'happy'],
    '😂': ['laugh crying', 'funny', 'lol'],
    '🥰': ['love', 'heart eyes', 'love'],
    '😢': ['sad', 'cry', 'tear'],
    '😠': ['angry', 'mad'],
    '😴': ['sleep', 'sleeping', 'zzz'],
    '🤔': ['think', 'thinking'],
    '😮': ['wow', 'surprised', 'surprise'],
    '🤗': ['hug', 'hugging'],
    '😇': ['angel', 'good'],
    '😎': ['cool', 'sunglasses'],
    '🥳': ['party', 'celebrate'],
    '🤩': ['star eyes', 'excited'],
    '😌': ['relaxed', 'calm'],
    '🥲': ['tear smile'],
    '😏': ['smirk'],
    '😋': ['yum', 'delicious', 'tasty'],
    '🎁': ['gift', 'present', 'birthday'],
    '🎈': ['balloon', 'birthday', 'party'],
    '🎀': ['ribbon', 'bow'],
    '🎊': ['confetti', 'party'],
    '🎉': ['party', 'celebrate'],
    '📚': ['book', 'read', 'library'],
    '✏️': ['pencil', 'write'],
    '🎓': ['graduation', 'school'],
    '🏠': ['house', 'home'],
    '🚗': ['car', 'vehicle'],
    '✈️': ['airplane', 'fly', 'travel'],
    '🚀': ['rocket', 'space', 'star'],
    '⏰': ['alarm clock', 'time'],
    '💡': ['light bulb', 'idea', 'light'],
    '🔔': ['bell', 'ring', 'notification'],
    '📷': ['camera', 'photo'],
    '🎩': ['top hat', 'hat'],
    '🧸': ['teddy bear', 'bear', 'toy']
};

/**
 * Open emoji picker
 */
function openEmojiPicker() {
    const picker = document.getElementById('emoji-picker');
    if (picker) {
        picker.classList.remove('hidden');
        emojiPickerOpen = true;
        renderEmojiGrid(activeCategory);
        // Focus search input
        const searchInput = picker.querySelector('.emoji-search');
        if (searchInput) {
            searchInput.value = '';
            searchInput.focus();
        }
    }
}

/**
 * Close emoji picker
 */
function closeEmojiPicker() {
    const picker = document.getElementById('emoji-picker');
    if (picker) {
        picker.classList.add('hidden');
        emojiPickerOpen = false;
    }
}

/**
 * Toggle emoji picker
 */
function toggleEmojiPicker() {
    if (emojiPickerOpen) {
        closeEmojiPicker();
    } else {
        openEmojiPicker();
    }
}

/**
 * Render emoji grid with emojis from a category
 * @param {string} category - Category name
 */
function renderEmojiGrid(category) {
    const grid = document.querySelector('.emoji-grid');
    if (!grid) return;

    const emojis = emojiCategories[category] || [];
    grid.innerHTML = '';

    emojis.forEach(emoji => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'emoji-item';
        button.textContent = emoji;
        button.onclick = () => selectEmoji(emoji);
        grid.appendChild(button);
    });
}

/**
 * Filter emojis by search term
 * @param {string} searchTerm - Search term
 */
function filterEmojis(searchTerm) {
    const grid = document.querySelector('.emoji-grid');
    if (!grid) return;

    const term = searchTerm.toLowerCase().trim();

    if (!term) {
        renderEmojiGrid(activeCategory);
        return;
    }

    const matchingEmojis = [];
    const matchedCategories = new Set();

    // Search in category names
    Object.keys(emojiCategories).forEach(category => {
        if (category.toLowerCase().includes(term)) {
            emojiCategories[category].forEach(emoji => {
                matchingEmojis.push(emoji);
                matchedCategories.add(category);
            });
        }
    });

    // Search in keywords
    Object.keys(emojiKeywords).forEach(emoji => {
        const keywords = emojiKeywords[emoji];
        for (const keyword of keywords) {
            if (keyword.includes(term)) {
                matchingEmojis.push(emoji);
                break;
            }
        }
    });

    // Remove duplicates and limit
    const uniqueEmojis = [...new Set(matchingEmojis)].slice(0, 48);

    grid.innerHTML = '';
    uniqueEmojis.forEach(emoji => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'emoji-item';
        button.textContent = emoji;
        button.onclick = () => selectEmoji(emoji);
        grid.appendChild(button);
    });
}

/**
 * Select an emoji and insert into input field
 * @param {string} emoji - Emoji character
 */
function selectEmoji(emoji) {
    const input = document.getElementById('emoji');
    if (input) {
        insertAtCursor(input, emoji);
        closeEmojiPicker();
        input.focus();
    }
}

/**
 * Insert text at cursor position in input field
 * @param {HTMLInputElement} field - Input field
 * @param {string} value - Text to insert
 */
function insertAtCursor(field, value) {
    if (field.selectionStart || field.selectionStart === '0') {
        const startPos = field.selectionStart;
        const endPos = field.selectionEnd;
        field.value = field.value.substring(0, startPos)
            + value
            + field.value.substring(endPos, field.value.length);
        // Move cursor after inserted emoji
        field.selectionStart = startPos + value.length;
        field.selectionEnd = startPos + value.length;
    } else {
        field.value += value;
    }
}

/**
 * Switch active category
 * @param {string} category - Category name
 */
function switchCategory(category) {
    activeCategory = category;

    // Update tab states
    const tabs = document.querySelectorAll('.emoji-category-tab');
    tabs.forEach(tab => {
        if (tab.dataset.category === category) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });

    // Clear search and render grid
    const searchInput = document.querySelector('.emoji-search');
    if (searchInput) {
        searchInput.value = '';
    }
    renderEmojiGrid(category);
}

/**
 * Enter edit mode for a story
 * @param {Object} story - Story object to edit
 */
function enterEditMode(story) {
    formMode = 'edit';
    editingStoryId = story.id;
    originalStoryData = { ...story };
    removeCoverFlag = false;

    // Pre-fill form fields
    document.getElementById('title').value = story.title;
    document.getElementById('emoji').value = story.emoji;
    document.getElementById('led_color').value = story.led_color;

    // Clear file inputs (they can't be pre-filled)
    document.getElementById('audio').value = '';
    document.getElementById('cover').value = '';

    // Show cover actions if story has cover
    if (story.cover_image) {
        coverActionsDiv.classList.remove('hidden');
        currentCoverName.textContent = `Current: ${story.cover_image}`;
    } else {
        coverActionsDiv.classList.add('hidden');
        currentCoverName.textContent = '';
    }

    updateFormUI();
    scrollToForm();
}

/**
 * Exit edit mode and reset form
 * @param {boolean} skipConfirm - Skip unsaved changes confirmation
 */
function exitEditMode(skipConfirm = false) {
    if (!skipConfirm && hasUnsavedChanges()) {
        if (!confirm('You have unsaved changes. Discard them?')) {
            return;
        }
    }

    formMode = 'upload';
    editingStoryId = null;
    originalStoryData = null;
    removeCoverFlag = false;

    uploadForm.reset();
    coverActionsDiv.classList.add('hidden');
    currentCoverName.textContent = '';

    updateFormUI();
}

/**
 * Update form UI based on current mode
 */
function updateFormUI() {
    const headerEl = document.querySelector('.upload-section h2');
    const submitBtn = uploadForm.querySelector('button[type="submit"]');
    const audioInput = document.getElementById('audio');

    if (formMode === 'edit') {
        headerEl.textContent = 'Edit Story';
        submitBtn.textContent = 'Save Changes';
        cancelEditBtn.classList.remove('hidden');
        audioInput.required = false;
    } else {
        headerEl.textContent = 'Upload New Story';
        submitBtn.textContent = 'Upload Story';
        cancelEditBtn.classList.add('hidden');
        audioInput.required = true;
    }
}

/**
 * Check if form has unsaved changes compared to original story
 * @returns {boolean}
 */
function hasUnsavedChanges() {
    if (formMode !== 'edit' || !originalStoryData) return false;

    const titleChanged = document.getElementById('title').value !== originalStoryData.title;
    const emojiChanged = document.getElementById('emoji').value !== originalStoryData.emoji;
    const colorChanged = document.getElementById('led_color').value !== originalStoryData.led_color;
    const audioSelected = document.getElementById('audio').files.length > 0;
    const coverSelected = document.getElementById('cover').files.length > 0;

    return titleChanged || emojiChanged || colorChanged || audioSelected || coverSelected || removeCoverFlag;
}

/**
 * Smooth scroll to upload form
 */
function scrollToForm() {
    document.querySelector('.upload-section').scrollIntoView({
        behavior: 'smooth',
        block: 'start'
    });
}

/**
 * Smooth scroll to a story card
 * @param {string} storyId - Story ID
 */
function scrollToCard(storyId) {
    const card = document.querySelector(`[data-story-id="${storyId}"]`);
    if (card) {
        card.scrollIntoView({
            behavior: 'smooth',
            block: 'center'
        });
    }
}

/**
 * Mark cover for removal
 */
function clearCover() {
    removeCoverFlag = true;
    document.getElementById('cover').value = '';
    currentCoverName.textContent = 'Cover will be removed on save';
    currentCoverName.style.color = 'var(--color-danger)';
}

/**
 * Update an existing story
 * @param {Event} event - Form submit event
 */
async function updateStory(event) {
    event.preventDefault();

    const formData = new FormData(uploadForm);
    formData.append('remove_cover', removeCoverFlag);

    // Remove audio field from FormData if no file selected
    // This prevents sending an empty file which causes validation errors
    const audioInput = document.getElementById('audio');
    if (audioInput.files.length === 0) {
        formData.delete('audio');
    }

    // Remove cover field from FormData if no file selected
    const coverInput = document.getElementById('cover');
    if (coverInput.files.length === 0) {
        formData.delete('cover');
    }

    const submitButton = uploadForm.querySelector('button[type="submit"]');

    try {
        submitButton.disabled = true;
        submitButton.textContent = 'Saving...';
        hideMessage();

        const response = await fetch(`/api/stories/${editingStoryId}`, {
            method: 'PUT',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update story');
        }

        const story = await response.json();
        showMessage(`Story "${story.title}" updated successfully!`, 'success');

        // Exit edit mode and reload list
        exitEditMode(true); // Skip confirm since we just saved
        await loadStories();

        // Scroll to updated card
        setTimeout(() => scrollToCard(story.id), 100);

    } catch (error) {
        console.error('Error updating story:', error);
        showMessage(error.message || 'Failed to update story', 'error');
        // Keep form populated for retry (don't reset)
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = 'Save Changes';
    }
}

/**
 * Initialize emoji picker event handlers
 */
function initEmojiPicker() {
    // Trigger button click
    const triggerBtn = document.querySelector('.emoji-trigger-btn');
    if (triggerBtn) {
        triggerBtn.onclick = toggleEmojiPicker;
    }

    // Click outside to close
    document.addEventListener('click', (event) => {
        const picker = document.getElementById('emoji-picker');
        const wrapper = document.querySelector('.emoji-input-wrapper');
        if (picker && !picker.contains(event.target) && !wrapper.contains(event.target)) {
            closeEmojiPicker();
        }
    });

    // Category tab clicks
    const tabs = document.querySelectorAll('.emoji-category-tab');
    tabs.forEach(tab => {
        tab.onclick = () => switchCategory(tab.dataset.category);
    });

    // Search input
    const searchInput = document.querySelector('.emoji-search');
    if (searchInput) {
        searchInput.addEventListener('input', (event) => {
            filterEmojis(event.target.value);
        });
    }
}

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

    // Edit button (first in action row)
    const editButton = document.createElement('button');
    editButton.className = 'btn btn-primary';
    editButton.textContent = 'Edit';
    editButton.style.cssText = 'padding: 0.5rem 0.75rem; font-size: 14px;';
    editButton.onclick = () => enterEditMode(story);
    actions.appendChild(editButton);

    // Assign/Unassign NFC button
    const nfcButton = document.createElement('button');
    nfcButton.className = story.nfc_uid ? 'btn btn-success' : 'btn btn-warning';
    nfcButton.textContent = story.nfc_uid ? 'Reassign NFC' : 'Assign NFC';
    nfcButton.style.cssText = 'padding: 0.5rem 0.75rem; font-size: 14px;';
    nfcButton.onclick = () => startNFCAssignment(story.id);
    actions.appendChild(nfcButton);

    // Delete button
    const deleteButton = document.createElement('button');
    deleteButton.className = 'btn btn-danger';
    deleteButton.textContent = 'Delete';
    deleteButton.style.cssText = 'padding: 0.5rem 0.75rem; font-size: 14px;';
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

    // Delegate to updateStory if in edit mode
    if (formMode === 'edit') {
        return updateStory(event);
    }

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
    initEmojiPicker();     // Initialize emoji picker

    // Edit mode event listeners
    cancelEditBtn.addEventListener('click', () => exitEditMode());
    clearCoverBtn.addEventListener('click', clearCover);
});

window.addEventListener('beforeunload', cleanup);

// Warn about unsaved changes on page navigation
window.addEventListener('beforeunload', (event) => {
    if (hasUnsavedChanges()) {
        event.preventDefault();
        event.returnValue = '';
    }
});
