// State machine
const STATES = {
    IDLE: 'idle',
    COLLECTING: 'collecting',
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
let collectingParams = []; // Parameter chips displayed during collection
const audioElement = document.getElementById('story-audio');

// UI Sound system
let uiAudioContext = null;
const soundBuffers = {};
const UI_SOUND_VOLUME = 0.3; // Keep sounds quiet

// Phase 16 D-04: pre-rendered bridge clips. Names match files preloaded below.
const BRIDGE_SOUND_NAMES = ['bridge_00', 'bridge_01', 'bridge_02', 'bridge_03', 'bridge_04'];

// Phase 16 D-06: buffered cover URL for THANKYOU swap. Reset per generation.
let bufferedCoverUrl = null;

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
            loadSound('chime', '/children/assets/chime.mp3'),
            // Phase 16 D-04: bridge clips for 3s threshold audio (D-02)
            loadSound('bridge_00', '/children/assets/bridge/00.wav').catch(() => null),
            loadSound('bridge_01', '/children/assets/bridge/01.wav').catch(() => null),
            loadSound('bridge_02', '/children/assets/bridge/02.wav').catch(() => null),
            loadSound('bridge_03', '/children/assets/bridge/03.wav').catch(() => null),
            loadSound('bridge_04', '/children/assets/bridge/04.wav').catch(() => null),
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

/**
 * Play a bridge audio clip at full volume. Returns the AudioBufferSourceNode
 * so the caller can .stop(0) it when narration arrives (D-03).
 * @param {string} name - Sound name (e.g. 'bridge_00')
 * @returns {AudioBufferSourceNode|null}
 */
function playBridgeSound(name) {
    if (!uiAudioContext || !soundBuffers[name]) return null;
    try {
        if (uiAudioContext.state === 'suspended') {
            uiAudioContext.resume();
        }
        const source = uiAudioContext.createBufferSource();
        const gainNode = uiAudioContext.createGain();
        source.buffer = soundBuffers[name];
        gainNode.gain.value = 1.0;
        source.connect(gainNode);
        gainNode.connect(uiAudioContext.destination);
        source.start(0);
        return source;
    } catch (err) {
        console.warn('Failed to play bridge sound', name, err);
        return null;
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
            case STATES.COLLECTING:
                stopLEDPulse();
                turnOffLED();
                stopProgressTracking();
                break;
            case STATES.IDLE:
                // Phase 16 D-06: reset cover buffer for next generation.
                bufferedCoverUrl = null;

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
                if (!story.generated) playAudio(story);
                startProgressTracking();
                break;
            case STATES.THANKYOU:
                // Reset pause state
                isPaused = false;
                pausedLEDState = null;
                document.querySelector('.pause-overlay')?.classList.add('hidden');
                document.querySelector('.pause-overlay')?.classList.remove('visible', 'resuming');
                document.querySelector('.screen-playing')?.classList.remove('paused');

                // Phase 16 D-06: apply buffered cover swap at THANKYOU transition.
                if (bufferedCoverUrl) {
                    applyCoverSwap(bufferedCoverUrl);
                }

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

// Parameter display functions
function renderParameterChips() {
    const container = document.getElementById('parameter-chips');
    container.innerHTML = '';
    collectingParams.forEach((param, i) => {
        const chip = document.createElement('span');
        chip.className = 'parameter-chip';
        chip.textContent = `${param.emoji} ${param.label}`;
        chip.style.animationDelay = `${i * 50}ms`;
        container.appendChild(chip);
    });
}

function clearParameterDisplay() {
    collectingParams = [];
    const display = document.getElementById('parameter-display');
    if (display) {
        display.classList.remove('visible');
    }
    const container = document.getElementById('parameter-chips');
    if (container) {
        container.innerHTML = '';
    }
}

function showThinkingOverlay() {
    const overlay = document.getElementById('thinking-overlay');
    if (overlay) {
        overlay.classList.add('visible');
        setTimeout(() => {
            overlay.classList.remove('visible');
            if (currentState === STATES.COLLECTING) {
                transitionTo(STATES.IDLE);
            }
        }, 2000);
    }
}

// Phase 16 D-06: replace the placeholder (chip-collage / cover-emoji) with the real cover URL.
function applyCoverSwap(url) {
    if (!url) return;
    const img = document.querySelector('.cover-image');
    const emoji = document.querySelector('.cover-emoji');
    const collage = document.getElementById('cover-chip-collage');
    if (img) {
        img.src = url;
        img.style.display = '';
    }
    if (emoji) emoji.style.display = 'none';
    if (collage) collage.hidden = true;
}

// Playback functions
function showPlaybackScreen(story) {
    const container = document.querySelector('[data-screen="playing"]');
    container.style.setProperty('--story-color', story.led_color);

    const cover = container.querySelector('.cover-image');
    const emoji = container.querySelector('.cover-emoji');
    const collage = document.getElementById('cover-chip-collage');

    if (story.cover_image) {
        cover.src = `/static/stories/${story.id}/${story.cover_image}`;
        cover.style.display = 'block';
        emoji.style.display = 'none';
        if (collage) collage.hidden = true;
    } else if (story && story.generated && !bufferedCoverUrl) {
        // Phase 16 D-07: chip-collage placeholder for generated stories before cover_ready.
        cover.style.display = 'none';
        emoji.style.display = 'none';
        if (collage) {
            collage.innerHTML = '';
            for (const p of (collectingParams || [])) {
                const chip = document.createElement('span');
                chip.className = 'parameter-chip';
                chip.textContent = (p && (p.label || p.value)) || '';
                collage.appendChild(chip);
            }
            collage.hidden = false;
        }
    } else {
        cover.style.display = 'none';
        emoji.style.display = 'block';
        emoji.textContent = story.emoji;
        if (collage) collage.hidden = true;
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
    // During generation playback, the audio queue controls THANKYOU transitions
    if (generationAudioQueue.isActive()) return;

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
            const data = JSON.parse(event.data);
            const { uid, card_type } = data;

            // Story card retap to pause/resume (existing behavior)
            if (card_type === 'story' && currentState === STATES.PLAYING && currentStory?.nfc_uid === uid) {
                togglePause();
                return;
            }

            // Parameter card — add to collection
            if (card_type === 'parameter') {
                if (currentState !== STATES.IDLE && currentState !== STATES.COLLECTING) return;

                playUISound('tap');
                collectingParams.push({
                    emoji: data.emoji || '🏷️',
                    label: data.label || data.value || '',
                    category: data.category || '',
                    value: data.value || '',
                });
                renderParameterChips();
                document.getElementById('parameter-display').classList.add('visible');

                if (currentState === STATES.IDLE) {
                    transitionTo(STATES.COLLECTING);
                }
                return;
            }

            // Go card — trigger generation with collected params, or show thinking if empty
            if (card_type === 'go') {
                if (collectingParams.length === 0) {
                    clearParameterDisplay();
                    showThinkingOverlay();
                } else {
                    // Phase 16 D-01: copy the just-collected chips into the thinking overlay so
                    // the child sees their choices while the AI is composing.
                    const thinkingChipsEl = document.getElementById('thinking-chips');
                    if (thinkingChipsEl) {
                        thinkingChipsEl.innerHTML = '';
                        for (const p of collectingParams) {
                            const chip = document.createElement('span');
                            chip.className = 'parameter-chip';
                            chip.textContent = (p && (p.label || p.value)) || '';
                            thinkingChipsEl.appendChild(chip);
                        }
                    }
                    const params = [...collectingParams];
                    clearParameterDisplay();
                    playUISound('tap');
                    unlockAudio();
                    startGeneration(params.map(p => ({ category: p.category, value: p.value })));
                }
                return;
            }

            // Story card — play normally, clear any collection
            if (card_type === 'story') {
                clearParameterDisplay();
                if (currentState !== STATES.IDLE && currentState !== STATES.COLLECTING) return;

                const response = await fetch(`/api/stories/nfc/${encodeURIComponent(uid)}`);
                if (response.ok) {
                    const story = await response.json();
                    playStory(story);
                }
                return;
            }

            // Unknown card — clear collection, return to idle
            if (card_type === 'unknown') {
                clearParameterDisplay();
                if (currentState !== STATES.IDLE) {
                    transitionTo(STATES.IDLE);
                }
                return;
            }

            // Legacy fallback (no card_type field)
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

// --- Generation audio queue ---
const generationAudioQueue = (() => {
    let pendingUrls = [];
    let streamComplete = false;
    let currentlyPlaying = false;
    let onCompleteCallback = null;

    function reset() {
        pendingUrls = [];
        streamComplete = false;
        currentlyPlaying = false;
        onCompleteCallback = null;
    }

    function enqueue(url) {
        pendingUrls.push(url);
        if (!currentlyPlaying) _playNext();
    }

    function markStreamComplete() {
        streamComplete = true;
        if (pendingUrls.length === 0 && !currentlyPlaying && onCompleteCallback) {
            onCompleteCallback();
        }
    }

    function onComplete(cb) {
        onCompleteCallback = cb;
    }

    function isActive() {
        return currentlyPlaying || pendingUrls.length > 0 || !streamComplete;
    }

    function _playNext() {
        if (pendingUrls.length === 0) return;
        const url = pendingUrls.shift();
        currentlyPlaying = true;
        audioElement.src = url;
        audioElement.currentTime = 0;
        audioElement.play().catch(err => {
            console.error('Queue playback failed:', err);
            currentlyPlaying = false;
            _onSegmentEnded();
        });
        audioElement.addEventListener('ended', _onSegmentEnded, { once: true });
    }

    function _onSegmentEnded() {
        if (pendingUrls.length > 0) {
            _playNext();
        } else {
            currentlyPlaying = false;
            if (streamComplete && onCompleteCallback) {
                onCompleteCallback();
            }
        }
    }

    return { reset, enqueue, markStreamComplete, onComplete, isActive };
})();

// --- SSE generation consumer ---
let _generationActive = false;

async function startGeneration(parameters) {
    if (_generationActive) return;
    _generationActive = true;

    generationAudioQueue.reset();

    // Phase 16 D-06: reset cover buffer for this generation.
    bufferedCoverUrl = null;

    // Phase 16 D-02 / D-03: 3-second bridge-audio gate.
    let bridgeNode = null;
    let bridgeFired = false;
    const bridgeTimer = setTimeout(() => {
        if (firstAudioReceived) return;
        bridgeFired = true;
        const idx = Math.floor(Math.random() * BRIDGE_SOUND_NAMES.length);
        bridgeNode = playBridgeSound(BRIDGE_SOUND_NAMES[idx]);
    }, 3000);

    const cancelBridge = () => {
        clearTimeout(bridgeTimer);
        if (bridgeNode) {
            try { bridgeNode.stop(0); } catch (_) { /* node may have ended */ }
            bridgeNode = null;
        }
    };

    // Diagnostic: cover round-trip timer (read manually on Jetson per VERIFICATION.md).
    console.time('cover-roundtrip');

    generationAudioQueue.onComplete(() => {
        _generationActive = false;
        transitionTo(STATES.THANKYOU);
    });

    const syntheticStory = {
        id: 'generated-' + Date.now(),
        title: 'Historia generada',
        emoji: '🤖',
        led_color: '#7C3AED',
        cover_image: null,
        audio_file: null,
        nfc_uid: null,
        generated: true,
    };
    transitionTo(STATES.PLAYING, syntheticStory);

    // Show thinking overlay (JS-controlled — no auto-hide timeout)
    const overlay = document.getElementById('thinking-overlay');
    if (overlay) overlay.classList.add('visible');

    let firstAudioReceived = false;
    console.time('first-audio-latency');

    try {
        const response = await fetch('/api/generate/story', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ parameters }),
        });

        if (!response.ok) {
            throw new Error(`Generation request failed: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split('\n\n');
            buffer = parts.pop();

            for (const part of parts) {
                for (const line of part.split('\n')) {
                    if (!line.startsWith('data: ')) continue;
                    let event;
                    try { event = JSON.parse(line.slice(6)); } catch { continue; }

                    if (event.audio_ready) {
                        if (event.audio_ready.error) {
                            console.warn('TTS synth failed for segment', event.audio_ready.index, event.audio_ready.error);
                        } else if (event.audio_ready.url) {
                            generationAudioQueue.enqueue(event.audio_ready.url);
                            if (!firstAudioReceived) {
                                cancelBridge();        // Phase 16 D-03: stop bridge clip the instant narration arrives.
                                firstAudioReceived = true;
                                if (overlay) overlay.classList.remove('visible');
                                console.timeEnd('first-audio-latency');
                            }
                        }
                    } else if (event.cover_ready) {
                        // Phase 16 D-06: buffer until THANKYOU. Don't swap during PLAYING.
                        bufferedCoverUrl = event.cover_ready.preview_url || null;
                        try { console.timeEnd('cover-roundtrip'); } catch (_) {}
                        // Edge case: if playback already finished (queue idle and we are still in PLAYING
                        // because the THANKYOU transition hasn't fired yet for some reason), apply now.
                        if (bufferedCoverUrl && !generationAudioQueue.isActive() && currentState === STATES.PLAYING) {
                            applyCoverSwap(bufferedCoverUrl);
                        }
                    } else if (event.cover_failed) {
                        // Phase 16 D-08: silent. Leave bufferedCoverUrl null → chip-collage stays through THANKYOU.
                    } else if (event.error && event.done) {
                        cancelBridge();
                        console.error('Generation error:', event.error);
                        generationAudioQueue.reset();
                        if (overlay) overlay.classList.remove('visible');
                        _generationActive = false;
                        transitionTo(STATES.IDLE);
                        return;
                    } else if (event.text === null && event.done === true) {
                        cancelBridge();
                        generationAudioQueue.markStreamComplete();
                        return;
                    }
                }
            }
        }

        // Stream ended without sentinel — mark complete
        generationAudioQueue.markStreamComplete();
    } catch (err) {
        cancelBridge();
        console.error('Generation fetch error:', err);
        generationAudioQueue.reset();
        if (overlay) overlay.classList.remove('visible');
        _generationActive = false;
        transitionTo(STATES.IDLE);
    }
}

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    stopLEDPulse();
    turnOffLED();
});
