(() => {
  "use strict";

  const WATCH_DURATION_MS = 2 * 60 * 1000;
  const SUCCESS_PHRASE = /\b(accepted|correct answer|all test cases passed|problem solved|solved successfully|submission successful)\b/i;
  const SUBMIT_PHRASE = /\b(submit|submit code|submit solution|judge)\b/i;
  const SOURCE_RESPONSE_TIMEOUT_MS = 1500;

  let observer = null;
  let disarmTimer = null;
  let capturePending = false;

  chrome.runtime.sendMessage({ type: "INJECT_MAIN_HELPER" }).catch(() => {});
  document.addEventListener("click", onDocumentClick, true);

  function onDocumentClick(event) {
    const control = event.target.closest("button, input[type='submit'], [role='button']");
    if (!control || !isSubmitLike(control)) return;
    armAcceptanceObserver();
  }

  function isSubmitLike(control) {
    const text = [
      control.innerText,
      control.value,
      control.getAttribute("aria-label"),
      control.getAttribute("title"),
      control.getAttribute("data-e2e-locator"),
      control.getAttribute("data-track-load")
    ].filter(Boolean).join(" ");
    return SUBMIT_PHRASE.test(text);
  }

  function armAcceptanceObserver() {
    disarmAcceptanceObserver();
    capturePending = false;
    observer = new MutationObserver((mutations) => {
      if (capturePending || !mutationsContainSuccess(mutations)) return;
      capturePending = true;
      disarmAcceptanceObserver();
      captureAcceptedSolution().catch((error) => {
        console.warn("DSA Solution Capture:", error.message);
      });
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true
    });
    disarmTimer = setTimeout(disarmAcceptanceObserver, WATCH_DURATION_MS);
  }

  function disarmAcceptanceObserver() {
    observer?.disconnect();
    observer = null;
    if (disarmTimer) clearTimeout(disarmTimer);
    disarmTimer = null;
  }

  function mutationsContainSuccess(mutations) {
    return mutations.some((mutation) => {
      if (mutation.type === "characterData") {
        return SUCCESS_PHRASE.test(mutation.target.textContent || "");
      }
      return [...mutation.addedNodes].some((node) => {
        const text = node.nodeType === Node.TEXT_NODE ? node.textContent : node.innerText || node.textContent;
        return SUCCESS_PHRASE.test(text || "");
      });
    });
  }

  async function captureAcceptedSolution() {
    const metadata = collectProblemMetadata();
    const source = await extractSource();
    if (!source) throw new Error("Accepted submission detected, but no source code was found.");

    const sourceHash = await sha256(source);
    const payload = {
      ...metadata,
      source,
      sourceHash,
      solvedAt: new Date().toISOString()
    };
    const result = await chrome.runtime.sendMessage({ type: "CAPTURE_SOLUTION", payload });
    if (!result?.ok) throw new Error(result?.error || "Capture request failed.");
  }

  function collectProblemMetadata() {
    const platform = detectPlatform();
    return {
      platform,
      problemId: detectProblemId(platform),
      problemName: detectProblemName(),
      problemUrl: `${location.origin}${location.pathname}`,
      language: detectLanguage(),
      tags: detectTags(platform)
    };
  }

  function detectPlatform() {
    if (location.hostname.includes("leetcode.com")) return "LEETCODE";
    if (location.hostname.includes("codeforces.com")) return "CODEFORCES";
    return "GEEKSFORGEEKS";
  }

  function detectProblemId(platform) {
    const path = location.pathname.split("/").filter(Boolean);
    if (platform === "LEETCODE") return path[path.indexOf("problems") + 1] || location.pathname;
    if (platform === "CODEFORCES") {
      const contestIndex = path.indexOf("contest");
      if (contestIndex >= 0) return `${path[contestIndex + 1]}-${path[contestIndex + 3]}`;
      const problemIndex = path.indexOf("problem");
      if (problemIndex >= 0) return `${path[problemIndex + 1]}-${path[problemIndex + 2]}`;
    }
    return path[path.indexOf("problems") + 1] || location.pathname;
  }

  function detectProblemName() {
    const selectors = [
      "[data-cy='question-title']",
      "[data-testid='problem-title']",
      ".problem-statement .title",
      "[class*='problem'] [class*='title']",
      "h1"
    ];
    for (const selector of selectors) {
      const text = document.querySelector(selector)?.textContent?.trim();
      if (text) return text.replace(/^\s*\d+[A-Z]?\.?\s*[-.]?\s*/, "");
    }
    return document.title.split(/[|–—]/)[0].trim() || detectProblemId(detectPlatform());
  }

  function detectLanguage() {
    const selectors = [
      "select[name='programTypeId'] option:checked",
      "[data-e2e-locator='console-select-language']",
      "[data-testid='language-select']",
      "[class*='language'] [role='button']",
      "[class*='language'] option:checked"
    ];
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      const text = element?.textContent?.trim() || element?.getAttribute("aria-label")?.trim();
      if (text && text.length < 80) return text;
    }
    return "unknown";
  }

  function detectTags(platform) {
    const selectors = platform === "CODEFORCES"
      ? [".tag-box"]
      : platform === "LEETCODE"
        ? ["a[href^='/tag/']", "[data-cy='topic-tag']"]
        : ["a[href*='/tag/']", "[class*='problem-tag']"];
    const tags = selectors.flatMap((selector) =>
      [...document.querySelectorAll(selector)].map((element) => element.textContent?.trim())
    );
    return [...new Set(tags.filter((tag) => tag && tag.length <= 100))].slice(0, 20);
  }

  async function extractSource() {
    const candidates = [];
    const add = (value) => {
      if (typeof value === "string" && value.trim().length >= 3) candidates.push(value.trim());
    };

    document.querySelectorAll("textarea").forEach((element) => add(element.value));
    document.querySelectorAll(".view-lines, .CodeMirror-code, .ace_text-layer")
      .forEach((element) => add(element.innerText || element.textContent));

    const mainWorldCandidates = await requestMainWorldSources();
    mainWorldCandidates.forEach((candidate) => add(candidate.value));
    return candidates.sort((left, right) => right.length - left.length)[0] || "";
  }

  function requestMainWorldSources() {
    return new Promise((resolve) => {
      const requestId = crypto.randomUUID();
      const timeout = setTimeout(() => {
        window.removeEventListener("message", onMessage);
        resolve([]);
      }, SOURCE_RESPONSE_TIMEOUT_MS);

      function onMessage(event) {
        if (event.source !== window ||
            event.data?.type !== "DSA_CAPTURE_SOURCE_RESPONSE" ||
            event.data.requestId !== requestId) return;
        clearTimeout(timeout);
        window.removeEventListener("message", onMessage);
        resolve(Array.isArray(event.data.candidates) ? event.data.candidates : []);
      }

      window.addEventListener("message", onMessage);
      window.postMessage({ type: "DSA_CAPTURE_REQUEST_SOURCE", requestId }, "*");
    });
  }

  async function sha256(value) {
    const bytes = new TextEncoder().encode(value);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
  }
})();
