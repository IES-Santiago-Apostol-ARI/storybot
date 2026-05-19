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

// Card registration state
let cardRegMode = null; // 'parameter' | 'go' | null
let capturedCardUID = null;

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
let activeCategory = 'Animales';

// Emoji Categories Data
const emojiCategories = {
    Animales: ['🐶', '🐱', '🐭', '🐰', '🦊', '🐻', '🐼', '🐨', '🐯', '🦁', '🐮', '🐷', '🐸', '🐵', '🐔', '🐧', '🐦', '🦆', '🦅', '🦉', '🦇', '🐺', '🐗', '🐴', '🦓', '🦒', '🦘', '🐘', '🦏', '🦛', '🦣', '🐅', '🐆', '🦌', '🦞', '🦑', '🦐', '🦀', '🐙', '🐚', '🐠', '🐟', '🦈', '🐋', '🐬', '🦭', '🦦', '🦩', '🕊️', '🦜', '🦚', '🦃', '🦢', '🦫', '🦝', '🦨', '🦡', '🦜', '🐢', '🐍', '🦎', '🦖', '🦕', '🐁', '🐀', '🐿️', '🦗', '🐛', '🦋', '🐝', '🐞', '🦟', '🦠'],
    Personajes: ['🐉', '👑', '🧙', '🧝', '🧚', '🤴', '👸', '👼', '🧞', '🤡', '👻', '🧌', '👹', '👺', '🦄', '💃', '🕺', '⚔️', '🛡️', '🔱', '⚡', '💎', '🏰', '🏯', '🗼', '🎠', '🎪', '🎭', '🧑‍🎨', '🧑‍🚒', '🧑‍⚖️', '🧑‍🔬', '🧑‍🎓'],
    Comida: ['🍎', '🍊', '🍋', '🍇', '🍓', '🫐', '🍑', '🍒', '🥕', '🥦', '🍞', '🥐', '🧀', '🍕', '🍰', '🍪', '🥛', '🍩'],
    Clima: ['☀️', '🌤️', '⛅', '🌧️', '❄️', '🌈', '☁️', '🌪️', '🔥', '🌊', '🌙', '⭐', '✨', '🌟', '🌈', '🌦️', '🌨️', '🌩️'],
    Actividades: ['🎨', '🎭', '🎪', '🎰', '🎲', '🎯', '🎳', '🎵', '🎶', '🎤', '🏃', '🚴', '🏊', '🎬', '🎮', '🏆', '⚽', '🏀', '🏈', '⚾', '🎾', '🏐', '🏉', '🥎', '🏏', '🏑', '🏒', '🥍', '🏓', '🏸', '🥊', '🥋', '🤼', '🤸', '⛹️', '🤺', '🤾', '⛷️', '🏂', '🎣', '🎽', '🎿', '⛸️', '🛷', '🛹', '🛼', '🛺', '🚣', '🚴', '🚵', '🤹', '🧗', '🧘', '🤿', '⛹️', '🏋️', '🤼', '🤸', '⛹️', '🤺', '🤾', '🎭', '🎪', '🎨', '🎬', '🎤', '🎧', '🎼', '🎹', '🎸', '🥁', '🎺', '🎷', '🎻'],
    Emociones: ['😊', '😄', '😂', '🥰', '😢', '😠', '😴', '🤔', '😮', '🤗', '😇', '😎', '🥳', '🤩', '😌', '🥲', '😏', '😋'],
    Objetos: ['🎁', '🎈', '🎀', '🎊', '🎉', '📚', '✏️', '🎓', '🏠', '🚗', '✈️', '🚀', '⏰', '💡', '🔔', '📷', '🎩', '🧸']
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
    '🧸': ['teddy bear', 'bear', 'toy'],
    '🦅': ['eagle', 'bird'],
    '🦉': ['owl', 'bird'],
    '🦇': ['bat', 'animal'],
    '🐺': ['wolf', 'wild'],
    '🐗': ['boar', 'wild boar'],
    '🐴': ['horse', 'animal'],
    '🦓': ['zebra', 'striped'],
    '🦒': ['giraffe', 'tall'],
    '🦘': ['kangaroo', 'jump'],
    '🐘': ['elephant', 'big'],
    '🦏': ['rhinoceros', 'rhino', 'horn'],
    '🦛': ['hippopotamus', 'hippo'],
    '🦣': ['mammoth', 'extinct'],
    '🐆': ['leopard', 'spotted'],
    '🦌': ['deer', 'animal'],
    '🦞': ['lobster', 'seafood'],
    '🦑': ['squid', 'sea'],
    '🦐': ['shrimp', 'seafood', 'sea'],
    '🦀': ['crab', 'seafood', 'sea'],
    '🐙': ['octopus', 'sea'],
    '🐚': ['seashell', 'shell', 'beach'],
    '🐠': ['fish', 'tropical', 'aquarium'],
    '🐟': ['fish', 'blowfish'],
    '🦈': ['shark', 'predator', 'dangerous'],
    '🐋': ['whale', 'sea', 'big'],
    '🐬': ['dolphin', 'sea', 'friendly'],
    '🦭': ['seal', 'sea'],
    '🦦': ['otter', 'cute', 'water'],
    '🦩': ['flamingo', 'pink', 'bird'],
    '🕊️': ['dove', 'peace', 'bird'],
    '🦚': ['peacock', 'bird', 'colorful'],
    '🦃': ['turkey', 'bird'],
    '🦢': ['swan', 'bird', 'elegant'],
    '🦫': ['beaver', 'animal'],
    '🦝': ['raccoon', 'animal', 'mask'],
    '🦨': ['skunk', 'animal'],
    '🦡': ['badger', 'animal'],
    '🐢': ['turtle', 'slow'],
    '🐍': ['snake', 'reptile'],
    '🦎': ['lizard', 'reptile'],
    '🦖': ['t-rex', 'dinosaur', 'extinct'],
    '🦕': ['sauropod', 'dinosaur', 'extinct'],
    '🐁': ['mouse', 'small'],
    '🐀': ['rat', 'rodent'],
    '🐿️': ['squirrel', 'nut'],
    '🦗': ['cricket', 'insect'],
    '🐛': ['bug', 'worm', 'insect'],
    '🦋': ['butterfly', 'insect', 'colorful'],
    '🐝': ['bee', 'insect', 'honey'],
    '🐞': ['ladybug', 'insect'],
    '🦟': ['mosquito', 'insect'],
    '🦠': ['virus', 'germ', 'bacteria'],
    '⚽': ['soccer', 'football', 'sport'],
    '🏀': ['basketball', 'sport'],
    '🏈': ['american football', 'sport'],
    '⚾': ['baseball', 'sport'],
    '🎾': ['tennis', 'sport'],
    '🏐': ['volleyball', 'sport'],
    '🏉': ['rugby', 'sport'],
    '🥎': ['softball', 'sport'],
    '🏏': ['cricket', 'sport'],
    '🏑': ['hockey', 'sport'],
    '🏒': ['ice hockey', 'sport'],
    '🥍': ['lacrosse', 'sport'],
    '🏓': ['ping pong', 'table tennis', 'sport'],
    '🏸': ['badminton', 'sport'],
    '🥊': ['boxing', 'sport', 'fight'],
    '🥋': ['martial arts', 'karate', 'sport'],
    '🤼': ['wrestling', 'sport'],
    '🤸': ['gymnastics', 'acrobat', 'sport'],
    '⛹️': ['basketball player', 'sport'],
    '🤺': ['fencing', 'sword', 'sport'],
    '🤾': ['handball', 'sport'],
    '⛷️': ['skiing', 'snow', 'sport'],
    '🏂': ['snowboarding', 'snow', 'sport'],
    '🎣': ['fishing', 'activity'],
    '🎿': ['skis', 'ski'],
    '⛸️': ['ice skating', 'winter', 'sport'],
    '🛷': ['sled', 'sledding', 'snow'],
    '🛹': ['skateboard', 'skateboarding', 'sport'],
    '🛼': ['roller skates', 'skating', 'sport'],
    '🚣': ['rowing', 'boat', 'water'],
    '🚵': ['mountain biking', 'bicycle', 'sport'],
    '🤹': ['juggling', 'juggler', 'circus'],
    '🧗': ['climbing', 'rock climbing', 'sport'],
    '🧘': ['yoga', 'meditation', 'exercise'],
    '🤿': ['diving', 'scuba', 'water'],
    '🏋️': ['weightlifting', 'exercise', 'gym'],
    '🎹': ['piano', 'keyboard', 'music'],
    '🎸': ['guitar', 'music'],
    '🥁': ['drums', 'percussion', 'music'],
    '🎺': ['trumpet', 'music'],
    '🎷': ['saxophone', 'music'],
    '🎻': ['violin', 'music'],
    '🐉': ['dragon', 'mythical', 'fire', 'magical'],
    '👑': ['king', 'queen', 'crown', 'royal', 'royalty'],
    '🧙': ['wizard', 'mage', 'sorcerer', 'magic', 'magical'],
    '🧝': ['elf', 'fairy tale', 'magical', 'wood elf'],
    '🧚': ['fairy', 'magical', 'wings', 'tiny'],
    '🤴': ['prince', 'royal', 'royalty'],
    '👸': ['princess', 'royal', 'royalty', 'lady'],
    '👼': ['angel', 'heaven', 'wings', 'holy'],
    '🧞': ['genie', 'magic', 'wish', 'lamp'],
    '🤡': ['clown', 'jester', 'funny', 'circus'],
    '👻': ['ghost', 'haunted', 'spooky', 'spirit'],
    '🧌': ['monster', 'ogre', 'scary', 'creature'],
    '👹': ['demon', 'ogre', 'scary', 'evil'],
    '👺': ['goblin', 'scary', 'evil', 'mischievous'],
    '🦄': ['unicorn', 'magical', 'mythical', 'horse'],
    '💃': ['dancer', 'dance', 'woman', 'performance'],
    '🕺': ['dancer', 'dance', 'man', 'performance'],
    '⚔️': ['sword', 'weapon', 'battle', 'knight'],
    '🛡️': ['shield', 'armor', 'protection', 'knight'],
    '🔱': ['trident', 'weapon', 'poseidon', 'power'],
    '⚡': ['lightning', 'power', 'magic', 'thunder', 'electricity'],
    '💎': ['jewel', 'treasure', 'diamond', 'gem', 'valuable'],
    '🏰': ['castle', 'palace', 'kingdom', 'royal', 'fortress'],
    '🏯': ['palace', 'tower', 'kingdom', 'fortress'],
    '🗼': ['tower', 'tall', 'structure', 'landmark'],
    '🎠': ['carousel', 'amusement', 'fair', 'horse'],
    '🎪': ['circus', 'tent', 'performance', 'show'],
    '🎭': ['theater', 'performance', 'mask', 'drama'],
    '🧑‍🎨': ['artist', 'painter', 'creative', 'art'],
    '🧑‍🚒': ['firefighter', 'hero', 'brave', 'rescue'],
    '🧑‍⚖️': ['judge', 'lawyer', 'law', 'justice'],
    '🧑‍🔬': ['scientist', 'research', 'smart', 'lab'],
    '🧑‍🎓': ['student', 'learning', 'school', 'education']
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
        currentCoverName.textContent = `Actual: ${story.cover_image}`;
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
        headerEl.textContent = 'Editar Historia';
        submitBtn.textContent = 'Guardar Cambios';
        cancelEditBtn.classList.remove('hidden');
        audioInput.required = false;
    } else {
        headerEl.textContent = 'Subir Nueva Historia';
        submitBtn.textContent = 'Subir Historia';
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
    currentCoverName.textContent = 'La portada se eliminará al guardar';
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
    console.log('DEBUG: audioInput.files.length:', audioInput.files.length);
    console.log('DEBUG: audioInput.files:', audioInput.files);
    if (audioInput.files.length === 0) {
        formData.delete('audio');
        console.log('DEBUG: audio field deleted from FormData');
    } else {
        console.log('DEBUG: audio file selected:', audioInput.files[0].name, 'size:', audioInput.files[0].size);
    }

    // Remove cover field from FormData if no file selected
    const coverInput = document.getElementById('cover');
    if (coverInput.files.length === 0) {
        formData.delete('cover');
    }

    const submitButton = uploadForm.querySelector('button[type="submit"]');

    try {
        submitButton.disabled = true;
        submitButton.textContent = 'Guardando...';
        hideMessage();

        const response = await fetch(`/api/stories/${editingStoryId}`, {
            method: 'PUT',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Error al actualizar la historia');
        }

        const story = await response.json();
        showMessage(`¡Historia "${story.title}" actualizada correctamente!`, 'success');

        // Exit edit mode and reload list
        exitEditMode(true); // Skip confirm since we just saved
        await loadStories();

        // Scroll to updated card
        setTimeout(() => scrollToCard(story.id), 100);

    } catch (error) {
        console.error('Error al actualizar la historia:', error);
        showMessage(error.message || 'Error al actualizar la historia', 'error');
        // Keep form populated for retry (don't reset)
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = 'Guardar Cambios';
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
        showMessage('Error al cargar historias. Por favor, actualiza la página.', 'error');
    }
}

/**
 * Render story list to DOM
 */
function renderStoryList() {
    if (stories.length === 0) {
        storyListContainer.innerHTML = '<p class="empty-state">Aún no hay historias. ¡Sube tu primera historia arriba!</p>';
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
        nfcStatus.textContent = 'Tarjeta NFC no asignada';
    }

    info.appendChild(title);
    info.appendChild(nfcStatus);

    const actions = document.createElement('div');
    actions.className = 'story-actions';

    // Edit button (first in action row)
    const editButton = document.createElement('button');
    editButton.className = 'btn btn-primary';
    editButton.textContent = 'Editar';
    editButton.style.cssText = 'padding: 0.5rem 0.75rem; font-size: 14px;';
    editButton.onclick = () => enterEditMode(story);
    actions.appendChild(editButton);

    // Assign/Unassign NFC button
    const nfcButton = document.createElement('button');
    nfcButton.className = story.nfc_uid ? 'btn btn-success' : 'btn btn-warning';
    nfcButton.textContent = story.nfc_uid ? 'Reasignar NFC' : 'Asignar NFC';
    nfcButton.style.cssText = 'padding: 0.5rem 0.75rem; font-size: 14px;';
    nfcButton.onclick = () => startNFCAssignment(story.id);
    actions.appendChild(nfcButton);

    // Delete button
    const deleteButton = document.createElement('button');
    deleteButton.className = 'btn btn-danger';
    deleteButton.textContent = 'Eliminar';
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
        submitButton.textContent = 'Subiendo...';
        hideMessage();

        const response = await fetch('/api/stories', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Error al subir la historia');
        }

        const story = await response.json();
        showMessage(`¡Historia "${story.title}" subida correctamente!`, 'success');

        // Reset form and reload list
        uploadForm.reset();
        await loadStories();

    } catch (error) {
        console.error('Error al subir la historia:', error);
        showMessage(error.message || 'Error al subir la historia', 'error');
    } finally {
        // Re-enable button
        submitButton.disabled = false;
        submitButton.textContent = 'Subir Historia';
    }
}

/**
 * Delete a story
 * @param {string} storyId - Story ID to delete
 * @param {string} storyTitle - Story title for confirmation
 */
async function deleteStory(storyId, storyTitle) {
    if (!confirm(`¿Estás seguro de que quieres eliminar "${storyTitle}"?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/stories/${storyId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error(`Failed to delete story: ${response.status}`);
        }

        showMessage(`Historia "${storyTitle}" eliminada`, 'success');
        await loadStories();

    } catch (error) {
        console.error('Error al eliminar la historia:', error);
        showMessage('Error al eliminar la historia', 'error');
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
    showMessage('Toca la tarjeta NFC para asignar...', 'info');

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
        console.error('Error de conexión NFC:', error);
        showMessage('Error de conexión NFC. Intenta de nuevo.', 'error');
        closeNFCConnection();
    });

    nfcEventSource.onerror = () => {
        showMessage('Error de conexión NFC. Intenta de nuevo.', 'error');
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
            throw new Error(error.detail || 'Error al asignar la tarjeta NFC');
        }

        const story = await response.json();
        showMessage(`Tarjeta NFC asignada a "${story.title}"`, 'success');
        closeNFCConnection();
        await loadStories();

    } catch (error) {
        console.error('Error al asignar NFC:', error);
        showMessage(error.message || 'Error al asignar la tarjeta NFC', 'error');
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
    let statusText = 'Desconocido';

    if (!hwState) {
        statusClass += ' disconnected';
        statusText = 'No disponible';
    } else if (hwState.status === 'ok') {
        statusClass += ' connected';
        statusText = hwState.is_mock ? 'Conectado (simulado)' : 'Conectado';
        if (hwState.is_mock) {
            statusClass += ' mock';
        }
    } else if (hwState.status === 'error') {
        statusClass += ' disconnected';
        statusText = hwState.error_message || 'Error';
    } else {
        statusClass += ' disconnected';
        statusText = 'No conectado';
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

/**
 * Load all registered cards from API
 */
async function loadCards() {
    const cardListEl = document.getElementById('card-list');
    try {
        const response = await fetch('/api/cards');
        if (!response.ok) throw new Error(`Failed to load cards: ${response.status}`);
        const data = await response.json();
        renderCardList(data.cards);
    } catch (error) {
        console.error('Error loading cards:', error);
        cardListEl.innerHTML = '<p class="empty-state">Error al cargar tarjetas.</p>';
    }
}

/**
 * Render the card list to DOM
 */
function renderCardList(cards) {
    const cardListEl = document.getElementById('card-list');

    if (!cards || cards.length === 0) {
        cardListEl.innerHTML = '<p class="empty-state">Aún no hay tarjetas registradas.</p>';
        return;
    }

    cardListEl.innerHTML = '';
    cards.forEach(card => {
        const item = document.createElement('div');
        item.className = 'card-item' + (card.type === 'go' ? ' card-item--go' : '');

        if (card.type === 'parameter') {
            const emoji = document.createElement('div');
            emoji.className = 'card-item-emoji';
            emoji.textContent = card.emoji || '🏷️';

            const info = document.createElement('div');
            info.className = 'card-item-info';

            const title = document.createElement('h4');
            title.className = 'card-item-title';
            title.textContent = card.label || card.value;

            const detail = document.createElement('p');
            detail.className = 'card-item-detail';
            detail.textContent = `${card.category}: ${card.value}`;

            info.appendChild(title);
            info.appendChild(detail);

            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'btn btn-danger';
            deleteBtn.textContent = 'Eliminar';
            deleteBtn.style.cssText = 'padding: 0.4rem 0.75rem; font-size: 13px;';
            deleteBtn.onclick = () => deleteCard(card.uid);

            item.appendChild(emoji);
            item.appendChild(info);
            item.appendChild(deleteBtn);
        } else if (card.type === 'go') {
            const emoji = document.createElement('div');
            emoji.className = 'card-item-emoji';
            emoji.textContent = '🚀';

            const info = document.createElement('div');
            info.className = 'card-item-info';

            const title = document.createElement('h4');
            title.className = 'card-item-title';
            title.textContent = 'Tarjeta Go';

            const detail = document.createElement('p');
            detail.className = 'card-item-detail';
            detail.textContent = `UID: ${card.uid}`;

            info.appendChild(title);
            info.appendChild(detail);

            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'btn btn-danger';
            deleteBtn.textContent = 'Eliminar';
            deleteBtn.style.cssText = 'padding: 0.4rem 0.75rem; font-size: 13px;';
            deleteBtn.onclick = () => deleteCard(card.uid);

            item.appendChild(emoji);
            item.appendChild(info);
            item.appendChild(deleteBtn);
        }

        cardListEl.appendChild(item);
    });
}

/**
 * Start card registration flow
 * @param {string} type - 'parameter' or 'go'
 */
function startCardRegistration(type) {
    cardRegMode = type;
    capturedCardUID = null;

    const overlay = document.getElementById('card-registration-overlay');
    const titleEl = document.getElementById('card-reg-title');
    const nfcStatus = document.getElementById('card-reg-nfc-status');
    const fields = document.getElementById('card-reg-fields');
    const goConfirm = document.getElementById('card-reg-go-confirm');
    const submitBtn = document.getElementById('card-reg-submit');

    overlay.classList.remove('hidden');
    titleEl.textContent = type === 'parameter' ? 'Registrar Parámetro' : 'Registrar Go';
    nfcStatus.classList.remove('hidden');
    nfcStatus.textContent = 'Toca la tarjeta NFC...';
    fields.classList.add('hidden');
    goConfirm.classList.add('hidden');
    submitBtn.classList.add('hidden');

    // Clear form fields
    document.getElementById('card-category').value = '';
    document.getElementById('card-value').value = '';
    document.getElementById('card-emoji-param').value = '';
    document.getElementById('card-label').value = '';

    // Close any existing NFC connection
    if (nfcEventSource) {
        nfcEventSource.close();
        nfcEventSource = null;
    }

    // Open NFC SSE for card capture
    nfcEventSource = new EventSource('/api/nfc/read');

    nfcEventSource.addEventListener('card', (event) => {
        try {
            const { uid } = JSON.parse(event.data);
            if (!capturedCardUID) {
                capturedCardUID = uid;
                nfcStatus.textContent = `Tarjeta capturada: ${uid}`;
                nfcStatus.classList.add('hidden');

                if (type === 'parameter') {
                    fields.classList.remove('hidden');
                    submitBtn.classList.remove('hidden');
                } else {
                    goConfirm.classList.remove('hidden');
                    submitBtn.classList.remove('hidden');
                }

                // Close NFC after capture
                nfcEventSource.close();
                nfcEventSource = null;
            }
        } catch (error) {
            console.error('Error parsing NFC card event:', error);
        }
    });

    nfcEventSource.onerror = () => {
        nfcStatus.textContent = 'Error de conexión NFC. Intenta de nuevo.';
        nfcStatus.style.color = 'var(--color-danger)';
    };
}

/**
 * Submit card registration
 */
async function submitCardRegistration() {
    if (!capturedCardUID || !cardRegMode) return;

    const payload = {
        uid: capturedCardUID,
        type: cardRegMode,
    };

    if (cardRegMode === 'parameter') {
        payload.category = document.getElementById('card-category').value.trim();
        payload.value = document.getElementById('card-value').value.trim();
        payload.emoji = document.getElementById('card-emoji-param').value.trim();
        payload.label = document.getElementById('card-label').value.trim();

        if (!payload.category || !payload.value || !payload.emoji || !payload.label) {
            showMessage('Todos los campos son obligatorios para tarjetas de parámetro.', 'error');
            return;
        }
    }

    try {
        const response = await fetch('/api/cards', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Error al registrar la tarjeta');
        }

        showMessage('Tarjeta registrada correctamente.', 'success');
        cancelCardRegistration();
        await loadCards();
    } catch (error) {
        console.error('Error registering card:', error);
        showMessage(error.message || 'Error al registrar la tarjeta', 'error');
    }
}

/**
 * Cancel card registration and close overlay
 */
function cancelCardRegistration() {
    cardRegMode = null;
    capturedCardUID = null;

    document.getElementById('card-registration-overlay').classList.add('hidden');

    if (nfcEventSource) {
        nfcEventSource.close();
        nfcEventSource = null;
    }
}

/**
 * Delete a registered card
 * @param {string} uid - Card UID to delete
 */
async function deleteCard(uid) {
    if (!confirm('¿Estás seguro de que quieres eliminar esta tarjeta?')) return;

    try {
        const response = await fetch(`/api/cards/${encodeURIComponent(uid)}`, {
            method: 'DELETE',
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Error al eliminar la tarjeta');
        }

        showMessage('Tarjeta eliminada.', 'success');
        await loadCards();
    } catch (error) {
        console.error('Error deleting card:', error);
        showMessage(error.message || 'Error al eliminar la tarjeta', 'error');
    }
}

/**
 * Initialize emoji picker for card registration form
 */
function initCardEmojiPicker() {
    const triggerBtn = document.getElementById('card-emoji-trigger');
    if (!triggerBtn) return;

    const picker = document.getElementById('card-emoji-picker');
    const input = document.getElementById('card-emoji-param');
    let cardPickerOpen = false;

    function renderCardEmojiGrid(category) {
        const grid = picker.querySelector('.emoji-grid');
        if (!grid) return;
        const emojis = emojiCategories[category] || [];
        grid.innerHTML = '';
        emojis.forEach(emoji => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'emoji-item';
            button.textContent = emoji;
            button.onclick = () => {
                input.value = emoji;
                picker.classList.add('hidden');
                cardPickerOpen = false;
            };
            grid.appendChild(button);
        });
    }

    triggerBtn.onclick = () => {
        if (cardPickerOpen) {
            picker.classList.add('hidden');
            cardPickerOpen = false;
        } else {
            picker.classList.remove('hidden');
            cardPickerOpen = true;
            renderCardEmojiGrid('Animales');
        }
    };

    // Category tabs
    picker.querySelectorAll('.emoji-category-tab').forEach(tab => {
        tab.onclick = () => {
            picker.querySelectorAll('.emoji-category-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            renderCardEmojiGrid(tab.dataset.category);
        };
    });

    // Search
    const searchInput = picker.querySelector('.emoji-search');
    if (searchInput) {
        searchInput.addEventListener('input', () => filterEmojis(searchInput.value));
    }

    // Close on outside click
    document.addEventListener('click', (event) => {
        if (cardPickerOpen && !picker.contains(event.target) && !triggerBtn.contains(event.target)) {
            picker.classList.add('hidden');
            cardPickerOpen = false;
        }
    });
}

function initPromoteEmojiPicker() {
    const triggerBtn = document.getElementById('promote-emoji-trigger');
    if (!triggerBtn) return;

    const picker = document.getElementById('promote-emoji-picker');
    const input = document.getElementById('promote-emoji');
    let promotePickerOpen = false;

    function renderPromoteEmojiGrid(category) {
        const grid = picker.querySelector('.emoji-grid');
        if (!grid) return;
        const emojis = emojiCategories[category] || [];
        grid.innerHTML = '';
        emojis.forEach(emoji => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'emoji-item';
            button.textContent = emoji;
            button.onclick = () => {
                input.value = emoji;
                picker.classList.add('hidden');
                promotePickerOpen = false;
            };
            grid.appendChild(button);
        });
    }

    triggerBtn.onclick = () => {
        if (promotePickerOpen) {
            picker.classList.add('hidden');
            promotePickerOpen = false;
        } else {
            picker.classList.remove('hidden');
            promotePickerOpen = true;
            renderPromoteEmojiGrid('Animales');
        }
    };

    picker.querySelectorAll('.emoji-category-tab').forEach(tab => {
        tab.onclick = () => {
            picker.querySelectorAll('.emoji-category-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            renderPromoteEmojiGrid(tab.dataset.category);
        };
    });

    const searchInput = picker.querySelector('.emoji-search');
    if (searchInput) {
        searchInput.addEventListener('input', () => filterEmojis(searchInput.value));
    }

    document.addEventListener('click', (event) => {
        if (promotePickerOpen && !picker.contains(event.target) && !triggerBtn.contains(event.target)) {
            picker.classList.add('hidden');
            promotePickerOpen = false;
        }
    });
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    loadStories();
    loadCards();
    uploadForm.addEventListener('submit', uploadStory);
    startStatusPolling();  // NEW: Start hardware status polling
    initEmojiPicker();     // Initialize emoji picker
    initCardEmojiPicker();
    initPromoteEmojiPicker();

    // Edit mode event listeners
    cancelEditBtn.addEventListener('click', () => exitEditMode());
    clearCoverBtn.addEventListener('click', clearCover);

    // Phase 16: Historias generadas (D-10, D-11, D-18)
    const promoteForm = document.getElementById('promote-form');
    if (promoteForm) promoteForm.addEventListener('submit', submitPromote);
    const promoteCancel = document.getElementById('promote-cancel');
    if (promoteCancel) promoteCancel.addEventListener('click', closePromoteModal);
    loadGeneratedStories();
});

window.addEventListener('beforeunload', cleanup);

// === Phase 16: Historias generadas (D-10, D-11, D-18) ===

let generatedStories = [];
let pendingPromoteId = null;

async function loadGeneratedStories() {
    const list = document.getElementById('generated-list');
    if (!list) return;
    try {
        const response = await fetch('/api/generated');
        if (!response.ok) {
            throw new Error('HTTP ' + response.status);
        }
        const data = await response.json();
        generatedStories = data.stories || [];
        renderGeneratedList();
    } catch (error) {
        console.error('Error loading generated stories:', error);
        list.innerHTML = '<p class="error">Error al cargar historias generadas.</p>';
    }
}

function renderGeneratedList() {
    const list = document.getElementById('generated-list');
    if (!list) return;
    if (!generatedStories.length) {
        list.innerHTML = '<p class="empty">No hay historias generadas pendientes.</p>';
        return;
    }
    list.innerHTML = '';
    for (const s of generatedStories) {
        list.appendChild(createGeneratedCard(s));
    }
}

function createGeneratedCard(story) {
    const card = document.createElement('div');
    card.className = 'generated-card';
    card.dataset.id = story.id;

    const title = document.createElement('h3');
    title.textContent = (story.text_preview || '').slice(0, 60) || story.id;
    card.appendChild(title);

    const meta = document.createElement('p');
    meta.className = 'generated-meta';
    const params = (story.parameters || []).map(p => p.label || p.value || '').filter(Boolean).join(' · ');
    meta.textContent = params;
    card.appendChild(meta);

    const actions = document.createElement('div');
    actions.className = 'generated-actions';

    const previewBtn = document.createElement('button');
    previewBtn.type = 'button';
    previewBtn.className = 'btn btn-secondary';
    previewBtn.textContent = 'Vista previa';
    previewBtn.addEventListener('click', () => previewGenerated(story.id));
    actions.appendChild(previewBtn);

    const printBtn = document.createElement('button');
    printBtn.type = 'button';
    printBtn.className = 'btn btn-secondary';
    printBtn.textContent = 'Imprimir pegatina';
    if (story.cover) {
        printBtn.addEventListener('click', () => openPrintPreview(story.id));
    } else {
        printBtn.disabled = true;
        printBtn.title = 'No hay portada para imprimir';
    }
    actions.appendChild(printBtn);

    const promoteBtn = document.createElement('button');
    promoteBtn.type = 'button';
    promoteBtn.className = 'btn btn-primary';
    promoteBtn.textContent = 'Promover → Asignar';
    promoteBtn.addEventListener('click', () => openPromoteModal(story.id));
    actions.appendChild(promoteBtn);

    const discardBtn = document.createElement('button');
    discardBtn.type = 'button';
    discardBtn.className = 'btn btn-danger';
    discardBtn.textContent = 'Descartar';
    discardBtn.addEventListener('click', () => discardGenerated(story.id));
    actions.appendChild(discardBtn);

    card.appendChild(actions);
    return card;
}

async function previewGenerated(id) {
    try {
        const response = await fetch('/api/generated/' + encodeURIComponent(id));
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const data = await response.json();
        const text = (data.text || '').slice(0, 600);
        const cover = data.cover && data.cover.preview ? '/static/generated/' + id + '/cover-preview.png' : null;
        let msg = text;
        if (cover) msg += '\n\n(Una imagen de portada se abrirá en otra pestaña.)';
        showMessage(msg || '(sin texto)', 'info');
        if (cover) window.open(cover, '_blank');
    } catch (e) {
        console.error('previewGenerated failed', e);
        showMessage('No se pudo cargar la vista previa.', 'error');
    }
}

async function discardGenerated(id) {
    if (!confirm('¿Descartar esta historia generada? Se eliminarán texto, audio y portada.')) return;
    try {
        const response = await fetch('/api/generated/' + encodeURIComponent(id), { method: 'DELETE' });
        if (!response.ok && response.status !== 204) {
            throw new Error('HTTP ' + response.status);
        }
        showMessage('Historia generada descartada.', 'success');
        await loadGeneratedStories();
    } catch (e) {
        console.error('discardGenerated failed', e);
        showMessage('Error al descartar la historia.', 'error');
    }
}

function openPromoteModal(id) {
    pendingPromoteId = id;
    const modal = document.getElementById('promote-modal');
    if (modal) modal.hidden = false;
    const titleInput = document.getElementById('promote-title');
    if (titleInput) titleInput.focus();
}

function closePromoteModal() {
    pendingPromoteId = null;
    const modal = document.getElementById('promote-modal');
    if (modal) modal.hidden = true;
    const form = document.getElementById('promote-form');
    if (form) form.reset();
}

async function submitPromote(event) {
    event.preventDefault();
    if (!pendingPromoteId) return;
    const title = document.getElementById('promote-title').value.trim();
    const emoji = document.getElementById('promote-emoji').value.trim();
    const led_color = document.getElementById('promote-led-color').value;
    try {
        const response = await fetch('/api/generated/' + encodeURIComponent(pendingPromoteId) + '/promote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, emoji, led_color }),
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error('HTTP ' + response.status + ': ' + (errData.detail || ''));
        }
        const newStory = await response.json();
        closePromoteModal();
        await loadGeneratedStories();
        if (typeof loadStories === 'function') await loadStories();
        if (typeof startNFCAssignment === 'function') {
            startNFCAssignment(newStory.id);
        }
    } catch (e) {
        console.error('submitPromote failed', e);
        showMessage('Error al promover la historia.', 'error');
    }
}

function openPrintPreview(storyId) {
    const url = '/static/generated/' + encodeURIComponent(storyId) + '/cover-print.png';
    const win = window.open('', '_blank');
    if (!win) {
        showMessage('Habilita las ventanas emergentes para imprimir.', 'error');
        return;
    }
    win.document.write(
        '<!doctype html><html><head><meta charset="utf-8">' +
        '<title>Imprimir portada</title>' +
        '<style>' +
        'html,body{margin:0;padding:0;background:#fff;}' +
        'body{display:flex;justify-content:center;align-items:center;min-height:100vh;}' +
        'img{max-width:100%;max-height:100vh;display:block;}' +
        '@media print{@page{margin:0;}body{min-height:auto;}}' +
        '</style></head><body>' +
        '<img src="' + url + '" alt="Portada" onload="window.focus();window.print();">' +
        '</body></html>'
    );
    win.document.close();
}

// Warn about unsaved changes on page navigation
window.addEventListener('beforeunload', (event) => {
    if (hasUnsavedChanges()) {
        event.preventDefault();
        event.returnValue = '';
    }
});
