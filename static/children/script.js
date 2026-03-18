// State machine
const STATES = {
    IDLE: 'idle',
    PLAYING: 'playing',
    THANKYOU: 'thankyou'
};

let currentState = STATES.IDLE;
let stories = [];
let currentStory = null;
let nfcEventSource = null;
let ledPulseInterval = null;
let progressAnimationId = null;
let isPaused = false;
let pausedLEDState = null; // { color, brightness, direction }
const audioElement = document.getElementById('story-audio');

// UI Sound system
let uiAudioContext = null;
const soundBuffers = {};
const UI_SOUND_VOLUME = 0.3; // Keep sounds quiet

/**
 * Initialize UI audio context and preload sounds
 * Must be called after user gesture due to autoplay policy
 */
async function initUISounds() {
    if (uiAudioContext) return; // Already initialized

    try {
        uiAudioContext = new (window.AudioContext || window.webkitAudioContext)();

        // Resume if suspended (browser autoplay policy)
        if (uiAudioContext.state === 'suspended') {
            await uiAudioContext.resume();
        }

        // Preload sound files
        await Promise.all([
            loadSound('tap', '/children/assets/tap.mp3'),
            loadSound('chime', '/children/assets/chime.mp3')
        ]);

        console.log('UI sounds initialized');
    } catch (err) {
        console.warn('UI sound initialization failed:', err);
    }
}

/**
 * Load a sound file into the buffer
 */
async function loadSound(name, url) {
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`Failed to fetch ${url}`);
        const arrayBuffer = await response.arrayBuffer();
        soundBuffers[name] = await uiAudioContext.decodeAudioData(arrayBuffer);
    } catch (err) {
        console.warn(`Failed to load sound ${name}:`, err);
    }
}

/**
 * Play a UI sound effect
 * @param {string} name - Sound name ('tap' or 'chime')
 * @param {number} volume - Volume multiplier (0-1), defaults to UI_SOUND_VOLUME
 */
function playUISound(name, volume = UI_SOUND_VOLUME) {
    if (!uiAudioContext || !soundBuffers[name]) return;

    try {
        // Resume context if suspended
        if (uiAudioContext.state === 'suspended') {
            uiAudioContext.resume();
        }

        const source = uiAudioContext.createBufferSource();
        const gainNode = uiAudioContext.createGain();

        source.buffer = soundBuffers[name];
        gainNode.gain.value = volume;

        source.connect(gainNode);
        gainNode.connect(uiAudioContext.destination);
        source.start(0);
    } catch (err) {
        console.warn(`Failed to play sound ${name}:`, err);
    }
}

function transitionTo(newState, story = null) {
    const previousState = currentState;
    currentState = newState;
    currentStory = story;

    // Get all pages
    const pages = document.querySelectorAll('.page');

    // First, set turning-out on current visible page
    pages.forEach(page => {
        if (page.classList.contains('page-visible')) {
            page.classList.remove('page-visible');
            page.classList.add('page-turning-out');
        }
    });

    // After a brief delay, hide the turned page and show new one
    setTimeout(() => {
        // Hide all screens first
        document.querySelectorAll('[data-screen]').forEach(screen => {
            screen.classList.add('hidden');
        });

        pages.forEach(page => {
            page.classList.remove('page-turning-out', 'page-visible');
            page.classList.add('page-hidden');
        });

        // Show the new page
        const newPage = document.querySelector(`[data-page="${newState}"]`);
        if (newPage) {
            newPage.classList.remove('page-hidden');
            newPage.classList.add('page-visible');
        }

        // Show the target screen (remove hidden class)
        const targetScreen = document.querySelector(`[data-screen="${newState}"]`);
        if (targetScreen) {
            targetScreen.classList.remove('hidden');
        }

        // Add playing class to screen-playing when in PLAYING state
        if (newState === STATES.PLAYING) {
            const playingScreen = document.querySelector('.screen-playing');
            if (playingScreen) {
                playingScreen.classList.add('playing');
            }
        } else {
            const playingScreen = document.querySelector('.screen-playing');
            if (playingScreen) {
                playingScreen.classList.remove('playing');
            }
        }

        // State-specific logic
        switch (newState) {
            case STATES.IDLE:
                // Reset pause state
                isPaused = false;
                pausedLEDState = null;
                document.querySelector('.pause-overlay')?.classList.add('hidden');
                document.querySelector('.pause-overlay')?.classList.remove('visible', 'resuming');
                document.querySelector('.screen-playing')?.classList.remove('paused');

                stopLEDPulse();
                turnOffLED();
                stopProgressTracking();
                break;
            case STATES.PLAYING:
                startLEDPulse(story.led_color);
                showPlaybackScreen(story);
                playAudio(story);
                startProgressTracking();
                break;
            case STATES.THANKYOU:
                // Reset pause state
                isPaused = false;
                pausedLEDState = null;
                document.querySelector('.pause-overlay')?.classList.add('hidden');
                document.querySelector('.pause-overlay')?.classList.remove('visible', 'resuming');
                document.querySelector('.screen-playing')?.classList.remove('paused');

                fadeLEDToIdle();
                stopProgressTracking();
                setTimeout(() => transitionTo(STATES.IDLE), 4000);
                break;
        }
    }, 100); // Small delay for the page-turning-out animation to start
}

// Story grid rendering
async function loadStories() {
    try {
        const response = await fetch('/api/stories');
        const data = await response.json();
        stories = data.stories;
        renderStoryGrid();
    } catch (err) {
        console.error('Failed to load stories:', err);
    }
}

function renderStoryGrid() {
    const grid = document.querySelector('.story-grid');
    const emptyState = document.getElementById('empty-state');

    grid.innerHTML = '';

    if (stories.length === 0) {
        // Show empty state, hide grid
        if (emptyState) emptyState.classList.remove('hidden');
        grid.style.display = 'none';
        return;
    }

    // Hide empty state, show grid
    if (emptyState) emptyState.classList.add('hidden');
    grid.style.display = ''; // Reset to CSS default (flex)

    stories.forEach((story, index) => {
        const card = document.createElement('div');
        card.className = 'story-card';
        card.style.backgroundColor = story.led_color + '40'; // 25% opacity
        card.style.setProperty('--card-index', index); // For staggered animation
        card.setAttribute('aria-label', story.title);
        card.textContent = story.emoji;
        card.onclick = () => playStory(story);
        grid.appendChild(card);
    });
}

function playStory(story) {
    if (currentState !== STATES.IDLE) return;

    // Immediately mark as playing to prevent duplicate NFC events
    currentState = STATES.PLAYING;

    // Play tap sound immediately for feedback
    playUISound('tap');

    // Ensure audio is unlocked before playing
    unlockAudio();

    // Add a small delay to ensure audio context is ready
    setTimeout(() => {
        transitionTo(STATES.PLAYING, story);
    }, 100);
}

// Playback functions
function showPlaybackScreen(story) {
    const container = document.querySelector('[data-screen="playing"]');
    container.style.setProperty('--story-color', story.led_color);

    const cover = container.querySelector('.cover-image');
    const emoji = container.querySelector('.cover-emoji');

    if (story.cover_image) {
        cover.src = `/static/stories/${story.id}/${story.cover_image}`;
        cover.style.display = 'block';
        emoji.style.display = 'none';
    } else {
        cover.style.display = 'none';
        emoji.style.display = 'block';
        emoji.textContent = story.emoji;
    }
}

function playAudio(story) {
    const audioPath = `/static/stories/${story.id}/${story.audio_file}`;
    console.log('Playing audio:', audioPath);
    console.log('Audio element:', audioElement);
    console.log('Audio src before:', audioElement.src);

    // Reset audio element
    audioElement.currentTime = 0;
    audioElement.src = audioPath;

    console.log('Audio src after:', audioElement.src);
    console.log('Audio readyState:', audioElement.readyState);

    // Try to play with better error handling
    const playPromise = audioElement.play();

    if (playPromise !== undefined) {
        playPromise.then(() => {
            console.log('Audio playback started successfully');
        }).catch(err => {
            console.error('Playback failed:', err);
            console.error('Error name:', err.name);
            console.error('Error message:', err.message);

            // If it's a permission error, the user needs to interact first
            if (err.name === 'NotAllowedError') {
                console.error('Autoplay prevented - user interaction required');
            }

            transitionTo(STATES.IDLE);
        });
    }
}

// Audio ended event handler
function handleAudioEnded() {
    console.log('Audio ended, transitioning to thank you');

    // Play chime sound for completion
    playUISound('chime');

    transitionTo(STATES.THANKYOU);
}

audioElement.addEventListener('ended', handleAudioEnded);

// Also handle audio errors
audioElement.addEventListener('error', (e) => {
    console.error('Audio error event:', e);
    console.error('Audio element error code:', audioElement.error);
    console.error('Audio element src:', audioElement.src);
    console.error('Audio element networkState:', audioElement.networkState);

    // Translate error code to message
    const errorMessages = {
        1: 'MEDIA_ERR_ABORTED - User aborted the audio',
        2: 'MEDIA_ERR_NETWORK - Network error occurred',
        3: 'MEDIA_ERR_DECODE - Audio decoding failed',
        4: 'MEDIA_ERR_SRC_NOT_SUPPORTED - Audio format not supported'
    };

    console.error('Error description:', errorMessages[audioElement.error?.code] || 'Unknown error');

    transitionTo(STATES.IDLE);
});

// Log when audio can play through
audioElement.addEventListener('canplaythrough', () => {
    console.log('Audio can play through - fully loaded');
});

// Log when audio starts playing
audioElement.addEventListener('play', () => {
    console.log('Audio play event fired');
});

// LED control functions
async function setLEDColor(color, brightness = 1.0) {
    try {
        await fetch('/api/system/led', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ color, brightness })
        });
    } catch (err) {
        console.error('LED control failed:', err);
    }
}

async function turnOffLED() {
    try {
        await fetch('/api/system/led/off', { method: 'POST' });
    } catch (err) {
        console.error('LED off failed:', err);
    }
}

function startLEDPulse(color) {
    // Start with full brightness
    setLEDColor(color, 1.0);

    // Pulse between 0.3 and 1.0 brightness
    let brightness = 1.0;
    let direction = -1;

    ledPulseInterval = setInterval(() => {
        brightness += direction * 0.1;
        if (brightness <= 0.3) {
            brightness = 0.3;
            direction = 1;
        } else if (brightness >= 1.0) {
            brightness = 1.0;
            direction = -1;
        }
        setLEDColor(color, brightness);
    }, 200); // Update every 200ms for smooth pulse
}

function stopLEDPulse() {
    if (ledPulseInterval) {
        clearInterval(ledPulseInterval);
        ledPulseInterval = null;
    }
}

function fadeLEDToIdle() {
    // Fade from current color to off over 2 seconds
    stopLEDPulse();
    let brightness = 1.0;
    const fadeInterval = setInterval(() => {
        brightness -= 0.1;
        if (brightness <= 0) {
            clearInterval(fadeInterval);
            turnOffLED();
        } else {
            setLEDColor(currentStory?.led_color || '#FFFFFF', brightness);
        }
    }, 200);
}

// Pause/Resume functions
function togglePause() {
    if (currentState !== STATES.PLAYING) return;

    playUISound('tap'); // Sound feedback for both pause and resume

    if (isPaused) {
        resumePlayback();
    } else {
        pausePlayback();
    }
    isPaused = !isPaused;
}

function pausePlayback() {
    // Pause audio immediately (no fade per user decision)
    audioElement.pause();

    // Show pause icon
    const pauseOverlay = document.querySelector('.pause-overlay');
    pauseOverlay.classList.remove('hidden', 'resuming');
    pauseOverlay.classList.add('visible');

    // Freeze animations via CSS class
    document.querySelector('.screen-playing').classList.add('paused');

    // Pause LED: stop pulse, hold at 0.6 brightness
    pauseLED();
}

function resumePlayback() {
    // Check if audio ended while paused
    if (audioElement.ended) {
        isPaused = false;
        transitionTo(STATES.THANKYOU);
        return;
    }

    // Resume audio
    audioElement.play();

    // Bounce-then-fade the pause icon
    const pauseOverlay = document.querySelector('.pause-overlay');
    pauseOverlay.classList.remove('visible');
    pauseOverlay.classList.add('resuming');

    // After animation, hide completely
    setTimeout(() => {
        pauseOverlay.classList.remove('resuming');
        pauseOverlay.classList.add('hidden');
    }, 400);

    // Unfreeze animations
    document.querySelector('.screen-playing').classList.remove('paused');

    // Resume LED with smooth ramp
    resumeLED();
}

function pauseLED() {
    if (ledPulseInterval && currentStory) {
        // Store current state for smooth resume
        pausedLEDState = { color: currentStory.led_color };
        stopLEDPulse();
        setLEDColor(currentStory.led_color, 0.6); // Hold at medium brightness
    }
}

function resumeLED() {
    if (pausedLEDState && currentStory) {
        // Ramp from 0.6 to 1.0 over 300ms, then restart normal pulse
        rampLEDBrightness(0.6, 1.0, currentStory.led_color, 300, () => {
            startLEDPulse(currentStory.led_color);
        });
        pausedLEDState = null;
    }
}

function rampLEDBrightness(from, to, color, duration, callback) {
    const steps = 10;
    const stepDuration = duration / steps;
    const stepChange = (to - from) / steps;
    let current = from;
    let step = 0;

    const rampInterval = setInterval(() => {
        current += stepChange;
        step++;
        setLEDColor(color, current);

        if (step >= steps) {
            clearInterval(rampInterval);
            if (callback) callback();
        }
    }, stepDuration);
}

// Progress tracking
function startProgressTracking() {
    const character = document.getElementById('progress-character');
    if (!character) return;

    function updateProgress() {
        if (audioElement.duration > 0) {
            const progress = audioElement.currentTime / audioElement.duration;
            // Move from 20px to (window.innerWidth - 80px)
            const maxX = window.innerWidth - 80;
            const x = 20 + (progress * (maxX - 20));
            character.style.left = x + 'px';
        }
        if (!audioElement.paused && !audioElement.ended) {
            progressAnimationId = requestAnimationFrame(updateProgress);
        }
    }

    // Reset position
    character.style.left = '20px';

    // Start tracking when audio plays
    audioElement.addEventListener('play', function onPlay() {
        progressAnimationId = requestAnimationFrame(updateProgress);
    }, { once: true });

    // Also start immediately if already playing
    if (!audioElement.paused) {
        progressAnimationId = requestAnimationFrame(updateProgress);
    }
}

function stopProgressTracking() {
    if (progressAnimationId) {
        cancelAnimationFrame(progressAnimationId);
        progressAnimationId = null;
    }
    // Reset character position
    const character = document.getElementById('progress-character');
    if (character) {
        character.style.left = '20px';
    }
}

// NFC listener
function startNFCListener() {
    nfcEventSource = new EventSource('/api/nfc/read');

    nfcEventSource.addEventListener('card', async (event) => {
        try {
            const { uid } = JSON.parse(event.data);

            if (currentState === STATES.PLAYING && currentStory?.nfc_uid === uid) {
                togglePause();
                return;
            }

            if (currentState !== STATES.IDLE) return;

            const response = await fetch(`/api/stories/nfc/${encodeURIComponent(uid)}`);
            if (response.ok) {
                const story = await response.json();
                playStory(story);
            }
        } catch (err) {
            console.error('NFC lookup failed:', err);
        }
    });

    nfcEventSource.addEventListener('error', () => {
        // Auto-reconnect built into EventSource
    });
}

// Audio unlock mechanism - must be called after user gesture
let audioUnlocked = false;

function unlockAudio() {
    if (audioUnlocked) return;

    console.log('Attempting to unlock audio...');

    // Create a silent audio file to unlock audio context
    const silentAudio = new Audio('data:audio/wav;base64,UklGRjIAAABXQVZFZm10IBIAAAABAAEAQB8AAEAfAAABAAgAAABmYWN0BAAAAAAAAABkYXRhAAAAAA==');

    const playPromise = silentAudio.play();

    if (playPromise !== undefined) {
        playPromise.then(() => {
            console.log('Audio unlocked successfully');
            audioUnlocked = true;
            silentAudio.pause();
            silentAudio.src = '';

            // Initialize UI sounds now that we have user gesture
            initUISounds();
        }).catch(err => {
            console.warn('Audio unlock failed:', err);
        });
    }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    // Initialize page states
    document.querySelectorAll('.page').forEach(page => {
        if (page.dataset.page === 'idle') {
            page.classList.add('page-visible');
        } else {
            page.classList.add('page-hidden');
        }
    });

    loadStories();
    startNFCListener();

    // Add pause/resume tap handler to playback container
    // Add both click (mouse) and touchstart (touchscreen kiosk) handlers
    const playbackContainer = document.querySelector('.playback-container');
    playbackContainer.addEventListener('click', togglePause);
    playbackContainer.addEventListener('touchstart', (e) => {
        e.preventDefault(); // Prevent the 300ms delayed click from also firing
        togglePause();
    }, { passive: false });

    // Unlock audio on first user interaction (touch/click)
    const unlockEvents = ['click', 'touchstart', 'keydown'];
    unlockEvents.forEach(eventType => {
        document.body.addEventListener(eventType, () => {
            unlockAudio();
        }, { once: true });
    });
});

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    stopLEDPulse();
    turnOffLED();
});
