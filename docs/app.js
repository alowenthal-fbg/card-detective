(function () {
  "use strict";

  // --- Config ----------------------------------------------------------------
  // Offset from Mystery Signature so the two prototypes land on different cards on the same day.
  const EPOCH = new Date(Date.UTC(2025, 11, 29));
  const ZOOM_SCALES = [10, 5, 3, 1.8, 1.0];
  const MAX_ATTEMPTS = ZOOM_SCALES.length;

  const els = {
    img:        document.getElementById("zoom-img"),
    frame:      document.getElementById("zoom-frame"),
    ladder:     document.getElementById("zoom-ladder"),
    hint:       document.getElementById("hint-line"),
    form:       document.getElementById("guess-form"),
    input:      document.getElementById("guess-input"),
    btn:        document.getElementById("guess-btn"),
    attempts:   document.getElementById("attempts-line"),
    feedback:   document.getElementById("feedback"),
    gameView:   document.getElementById("game-view"),
    revealView: document.getElementById("reveal-view"),
    revealTitle:   document.getElementById("reveal-title"),
    revealTagline: document.getElementById("reveal-tagline"),
    revealCard:    document.getElementById("reveal-card-img"),
    revealPlayer:  document.getElementById("reveal-player"),
    revealContext: document.getElementById("reveal-context"),
    revealStory:   document.getElementById("reveal-story"),
    bidLink:       document.getElementById("bid-link"),
    moreLink:      document.getElementById("more-link"),
    shareBtn:      document.getElementById("share-btn"),
    nextTime:      document.getElementById("next-time"),
    dateLine:      document.getElementById("date-line"),
    streakNum:     document.getElementById("streak-num"),
  };

  const STORAGE_STREAK    = "carddet_streak";
  const STORAGE_LAST_DATE = "carddet_last_date";

  let state = { cards: [], today: null, attempts: 0, done: false };

  // --- Date helpers ---------------------------------------------------------
  function todayKey() { return new Date().toISOString().slice(0, 10); }
  function daysSinceEpoch() {
    const now = new Date();
    const utcMidnight = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.floor((utcMidnight - EPOCH.getTime()) / 86400000);
  }
  function setDateLine() {
    const opts = { weekday: "long", month: "long", day: "numeric" };
    els.dateLine.textContent = new Date().toLocaleDateString(undefined, opts);
  }

  // --- Streak ---------------------------------------------------------------
  function loadStreak() {
    const s = parseInt(localStorage.getItem(STORAGE_STREAK) || "0", 10);
    els.streakNum.textContent = s;
  }
  function saveStreakOnFinish(won) {
    const today = todayKey();
    const last = localStorage.getItem(STORAGE_LAST_DATE);
    if (last === today) return;
    let s = parseInt(localStorage.getItem(STORAGE_STREAK) || "0", 10);
    s = won ? s + 1 : 0;
    localStorage.setItem(STORAGE_STREAK, String(s));
    localStorage.setItem(STORAGE_LAST_DATE, today);
    els.streakNum.textContent = s;
  }

  // --- Guess matching -------------------------------------------------------
  const SUFFIXES = new Set(["jr", "sr", "ii", "iii", "iv"]);
  function normalize(name) {
    if (!name) return "";
    name = name.normalize("NFKD").replace(/[̀-ͯ]/g, "");
    name = name.toLowerCase().replace(/[^a-z0-9 ]/g, " ");
    return name.replace(/\s+/g, " ").trim();
  }
  function tokens(name) {
    return normalize(name).split(" ").filter(t => t && !SUFFIXES.has(t));
  }
  function isMatch(guess, canonical) {
    const g = tokens(guess);
    const c = tokens(canonical);
    if (!g.length) return false;
    const last = g[g.length - 1];
    const lastInC = c.includes(last) || c.some(t => t.startsWith(last));
    if (!lastInC) return false;
    if (g.length > 1) {
      const first = g[0];
      const firstInC = c.includes(first) || c.some(t => t.startsWith(first));
      if (!firstInC) return false;
    }
    return true;
  }

  // --- Zoom + ladder UI -----------------------------------------------------
  function applyZoom(rung, focal) {
    const scale = ZOOM_SCALES[Math.min(rung, ZOOM_SCALES.length - 1)];
    const ox = (focal.x * 100).toFixed(1) + "%";
    const oy = (focal.y * 100).toFixed(1) + "%";
    els.img.style.transformOrigin = `${ox} ${oy}`;
    els.img.style.transform = `scale(${scale})`;
    els.frame.dataset.rung = String(rung);
  }
  function paintLadder(rung) {
    Array.from(els.ladder.querySelectorAll(".rung")).forEach((el) => {
      const r = parseInt(el.dataset.rung, 10);
      el.classList.toggle("passed", r < rung);
      el.classList.toggle("active", r === rung);
    });
  }
  function setHintForRung(rung, detailLabel) {
    if (rung === 0) {
      els.hint.innerHTML =
        `Whose card is this? <span class="detail-pill">${detailLabel}</span>`;
    } else if (rung < MAX_ATTEMPTS - 1) {
      els.hint.textContent = "Camera pulled back. Take another guess.";
    } else {
      els.hint.textContent = "Last look at the full card.";
    }
  }
  function setAttempts(n) {
    state.attempts = n;
    els.attempts.textContent =
      `Guess ${Math.min(n + 1, MAX_ATTEMPTS)} of ${MAX_ATTEMPTS}`;
  }
  function clearFeedback() { els.feedback.textContent = ""; els.feedback.className = "feedback"; }
  function setFeedback(text, kind) {
    els.feedback.textContent = text;
    els.feedback.className = "feedback " + (kind || "");
  }

  // --- Reveal ---------------------------------------------------------------
  function showReveal(card, won, attempts) {
    els.gameView.hidden = true;
    els.revealView.hidden = false;
    if (won) {
      els.revealTitle.textContent = attempts === 1 ? "Eagle eye!" : "Caught it.";
      els.revealTitle.className = "win";
      els.revealTagline.textContent = attempts === 1
        ? "Solved on the tightest crop."
        : `Solved in ${attempts} guess${attempts === 1 ? "" : "es"}.`;
    } else {
      els.revealTitle.textContent = "Tough one.";
      els.revealTitle.className = "lose";
      els.revealTagline.textContent = "Better luck tomorrow.";
    }
    els.revealCard.src = card.card_path;
    els.revealPlayer.textContent = card.player;
    els.revealContext.textContent =
      `${card.team} · ${card.position} · ${card.era}` +
      (card.year ? ` · ${card.year}` : "");
    els.revealStory.textContent = card.story;
    els.bidLink.href = card.listing_url;
    els.moreLink.href = `https://www.fanaticscollect.com/marketplace?type=WEEKLY&q=${encodeURIComponent(card.player)}`;
    els.moreLink.textContent = `See more ${card.player} cards`;

    els.shareBtn.onclick = () => {
      const lines = [
        `Card Detective · ${todayKey()}`,
        won ? `Solved in ${attempts}/${MAX_ATTEMPTS} 🔍` : `Stumped today.`,
        location.href,
      ];
      if (navigator.share) {
        navigator.share({ text: lines.join("\n") });
      } else {
        navigator.clipboard.writeText(lines.join("\n")).then(() => {
          els.shareBtn.textContent = "Copied!";
          setTimeout(() => (els.shareBtn.textContent = "Share my result"), 1500);
        });
      }
    };

    saveStreakOnFinish(won);
    startCountdown();
  }

  function startCountdown() {
    function tick() {
      const now = new Date();
      const tomorrow = new Date(now);
      tomorrow.setHours(24, 0, 0, 0);
      const ms = tomorrow - now;
      const h = Math.floor(ms / 3600000);
      const m = Math.floor((ms % 3600000) / 60000);
      const s = Math.floor((ms % 60000) / 1000);
      els.nextTime.textContent =
        String(h).padStart(2, "0") + ":" +
        String(m).padStart(2, "0") + ":" +
        String(s).padStart(2, "0");
    }
    tick();
    setInterval(tick, 1000);
  }

  // --- Game flow ------------------------------------------------------------
  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const guess = els.input.value.trim();
    if (!guess || state.done) return;
    clearFeedback();

    const correct = isMatch(guess, state.today.player);
    const newAttempts = state.attempts + 1;
    setAttempts(newAttempts);

    if (correct || newAttempts >= MAX_ATTEMPTS) {
      state.done = true;
      els.btn.disabled = true;
      applyZoom(MAX_ATTEMPTS - 1, state.today.focal);
      paintLadder(MAX_ATTEMPTS - 1);
      setTimeout(() => showReveal(state.today, correct, newAttempts), 500);
      return;
    }

    const newRung = newAttempts; // 0 was initial; after 1 wrong → rung 1, etc.
    applyZoom(newRung, state.today.focal);
    paintLadder(newRung);
    setHintForRung(newRung, state.today.detail_label);
    setFeedback("Not it. Camera pulled back.", "wrong");
    els.input.value = "";
    els.input.focus();
  });

  // --- Boot -----------------------------------------------------------------
  async function init() {
    setDateLine();
    loadStreak();
    const r = await fetch("./cards.json");
    state.cards = await r.json();
    const idx = ((daysSinceEpoch() % state.cards.length) + state.cards.length) % state.cards.length;
    state.today = state.cards[idx];
    els.img.src = state.today.card_path;
    setAttempts(0);
    applyZoom(0, state.today.focal);
    paintLadder(0);
    setHintForRung(0, state.today.detail_label);
  }

  init().catch((err) => {
    console.error(err);
    setFeedback("Failed to load today's puzzle.", "wrong");
  });
})();
