// Minimal launcher for the bundled game. Saves use the engine's native IDBFS.
const statusElement = document.getElementById('status');
const startButton = document.getElementById('click-to-play-button');
const isMobile = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
const isTouch = isMobile && window.matchMedia('(pointer: coarse)').matches;
const textDecoder = new TextDecoder();
document.body.dataset.isTouch = isTouch ? 1 : 0;
let ready = false;
let started = false;
const qualitySelect = document.getElementById('quality');
const requestedQuality = new URLSearchParams(location.search).get('quality');
qualitySelect.value = ['low', 'full'].includes(requestedQuality) ? requestedQuality : 'auto';
qualitySelect.addEventListener('change', () => {
    const url = new URL(window.top.location.href);
    if (qualitySelect.value === 'auto') url.searchParams.delete('quality');
    else url.searchParams.set('quality', qualitySelect.value);
    window.top.location.assign(url.href);
});

function failGame(error) {
    console.error(error);
    document.querySelector('.start-container').hidden = false;
    statusElement.textContent = 'Unable to start the game. Reload to try again.';
    startButton.hidden = false;
    startButton.disabled = false;
    startButton.textContent = 'Reload game';
    startButton.onclick = () => window.top.location.reload();
}

function setStatus(text) {
    if (started && text) statusElement.textContent = 'Starting game…';
}

window.addEventListener('message', (event) => {
    if (event.source !== window.parent || event.origin !== location.origin) return;
    if (event.data?.event === 'launcher.progress' && !started) {
        ready = event.data.ready === true;
        startButton.disabled = !ready;
        statusElement.textContent = ready ? '' : event.data.text || 'Loading game…';
    }
});

startButton.addEventListener('click', () => {
    if (!ready || started) return;
    started = true;
    startButton.disabled = true;
    startButton.hidden = true;
    statusElement.textContent = 'Starting game…';
    // Keep the real user gesture for browser audio and fullscreen permissions.
    document.getElementById('canvas').focus();
    loadGame().catch(failGame);
});
