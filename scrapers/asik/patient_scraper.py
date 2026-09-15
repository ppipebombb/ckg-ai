"""
=============================================================================
Patient Detail Scraper Module
=============================================================================
Deep-scrapes individual patient data from the CKG Pelayanan detail page.

For each patient, this module:
  1. Clicks "Mulai" from the patient list to enter the detail page
  2. Reads the patient info card (name, NIK, DOB, age, gender, etc.)
  3. Clicks "Detail Data" to open the info dialog, reads it, closes with "Tutup"
  4. Scrapes "Pemeriksaan Mandiri" — clicks "Input Data" for green-checked items,
     reads form values, goes back WITHOUT submitting
  5. Scrapes "Pelayanan oleh Nakes" — clicks "Input Data" for items with
     green "Ya" toggle + "Selesai diperiksa" status, reads form values, goes back
  6. Returns to the patient list

SAFETY: Never clicks "Kirim", "Selesaikan Layanan", or any submit button.
=============================================================================
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Page
from rich.console import Console

from helpers.auth import SessionExpiredError

console = Console()

# Default form-tab batch size. Env-override: ASIK_FORM_BATCH_SIZE.
# Higher = more concurrent tab opens per batch, fewer batches per patient.
# Risk: more concurrent fetches to form.kemkes.go.id (server throttle).
# Probe showed batch=4 → 1.87s for 4 forms, batch=8 with 4 forms → 2.12s.
# For high-form patients (10+ forms), batch=8 saves ~30% wall time.
_DEFAULT_BATCH_SIZE = int(os.environ.get("ASIK_FORM_BATCH_SIZE", "8"))

# Indonesian month names — for formatting API `YYYY-MM-DD` → "17 April 1976"
_ID_MONTHS = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"

# Buttons we must NEVER click
DANGEROUS_BUTTONS = [
    "kirim", "submit", "selesaikan", "simpan", "save",
    "selesaikan layanan", "kirim rapor",
]


def is_dangerous_button(text: str) -> bool:
    """Check if a button text is one we should never click."""
    return text.strip().lower() in DANGEROUS_BUTTONS


def _batch_read_forms_via_tabs(context, form_items: list[dict],
                               batch_size: int | None = None,
                               tab_pool: list | None = None) -> list[dict]:
    """Open form URLs in browser tabs and read form data.

    Strategy (Option 1 + 3 from probe research):
      - **Commit-style goto**: ``wait_until="commit"`` returns as soon as the
        navigation network response is received, before HTML parsing
        finishes. We can fire N gotos in quick succession then wait for
        DOMContentLoaded in a second loop. Server-render of all batch
        tabs runs concurrently.
      - **Tab pool reuse** (if ``tab_pool`` is passed): caller owns the pool
        of pre-opened pages. Each form reuses a pool tab via ``tab.goto``
        instead of ``context.new_page()`` (saves ~67ms per form, eliminates
        tab close overhead).

    Race condition on the form page: SurveyJS renders question labels
    before it receives/decrypts the answer XHR from
    ``/cha/cha-formbuilder/.../skrining-layanan``. To avoid reading a DOM
    that hasn't had its answers applied yet:
      1. Subscribe a per-tab response listener that flips a flag when
         skrining-layanan returns 200.
      2. After goto + DOMContentLoaded, poll the flag (up to 6s).
      3. Fixed 120ms wait so SurveyJS applies the decrypted answers.
      4. Read once with `_read_all_form_fields`.

    Listener is removed after each form to prevent stale-response races
    when the tab is reused in the pool.

    SAFETY: Only reads form fields — never clicks submit buttons.
    """
    if batch_size is None:
        batch_size = _DEFAULT_BATCH_SIZE
    # Pre-size and assign by ABSOLUTE index so the returned list always matches
    # `form_items` order. A tab-open failure appends in pass 1 and a success in
    # pass 2, so positional `append` would otherwise float failures ahead of
    # successes — corrupting any caller that maps results back by position
    # (e.g. the Tatalaksana per-row form mapping).
    results: list = [None] * len(form_items)
    own_pool = tab_pool is None
    if own_pool:
        tab_pool = []

    for batch_start in range(0, len(form_items), batch_size):
        batch = form_items[batch_start:batch_start + batch_size]

        # Grow pool if needed.
        while len(tab_pool) < len(batch):
            tab_pool.append(context.new_page())

        # Pass 1: fire commit-style gotos. Each goto returns ~immediately
        # after the network connection, so all N tabs in the batch start
        # loading server-side in parallel.
        active = []  # list of (abs_idx, item, tab, flag, listener_handle)
        for i, item in enumerate(batch):
            abs_idx = batch_start + i
            if not item.get("url"):
                results[abs_idx] = {"layanan": item["layanan"], "form_data": {}}
                continue
            tab = tab_pool[i]
            answer_flag = {"seen": False}

            def _on_response(resp, flag=answer_flag):
                if "skrining-layanan" in resp.url and resp.status == 200:
                    flag["seen"] = True

            try:
                tab.on("response", _on_response)
                tab.goto(item["url"], wait_until="commit", timeout=20000)
                active.append((abs_idx, item, tab, answer_flag, _on_response))
            except Exception as e:
                console.print(f"          [yellow]Tab open failed for '{item['layanan']}': {e}[/yellow]")
                # Mark the failure so callers can tell it apart from a form that
                # was read fine but is genuinely empty.
                results[abs_idx] = {"layanan": item["layanan"], "form_data": {}, "error": f"tab open failed: {e}"}
                try:
                    tab.remove_listener("response", _on_response)
                except Exception:
                    pass

        # Pass 2: wait for DOMContentLoaded + XHR + parse for each tab.
        for abs_idx, item, tab, answer_flag, listener in active:
            try:
                try:
                    tab.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass
                try:
                    tab.wait_for_selector(
                        '.sd-question[data-name], .sd-question[id^="sq_"]',
                        timeout=4000,
                    )
                except Exception:
                    pass

                if item.get("has_answers", True):
                    _poll_flag(tab, answer_flag, timeout_ms=6000, poll_ms=30)
                    tab.wait_for_timeout(120)

                form_data = _read_all_form_fields(tab)
                if not item.get("has_answers", True):
                    form_data = {
                        k: (v if k.startswith("_") else None)
                        for k, v in form_data.items()
                    }
                results[abs_idx] = {"layanan": item["layanan"], "form_data": form_data}
            except Exception as e:
                console.print(f"          [yellow]Tab read failed for '{item['layanan']}': {e}[/yellow]")
                results[abs_idx] = {"layanan": item["layanan"], "form_data": {}, "error": f"tab read failed: {e}"}
            finally:
                # Remove listener so a reused tab doesn't see stale responses
                # leaking into the next form's answer_flag.
                try:
                    tab.remove_listener("response", listener)
                except Exception:
                    pass

    if own_pool:
        for tab in tab_pool:
            try:
                tab.close()
            except Exception:
                pass

    # Every slot is assigned above; guard against an unexpected gap so callers
    # never receive a None.
    return [r if r is not None else {"layanan": "", "form_data": {}, "error": "no result"}
            for r in results]


def _poll_flag(tab, flag: dict, timeout_ms: int, poll_ms: int = 50) -> None:
    """Block until `flag['seen']` is True or timeout expires."""
    elapsed = 0
    while not flag.get("seen") and elapsed < timeout_ms:
        tab.wait_for_timeout(poll_ms)
        elapsed += poll_ms


# =============================================================================
# Read all form fields from the current page
# =============================================================================
def _read_all_form_fields(page: Page) -> dict:
    """
    Read all visible form fields and their current values.
    Handles: text inputs, number inputs, radio buttons, checkboxes,
    select dropdowns, textareas, and display-only text.

    Returns a dict of { question_label: answer_value }
    """
    form_data = page.evaluate("""() => {
        const result = {};
        // Coerce defensively: some custom SurveyJS widgets (e.g. the tatalaksana
        // Diagnosis/Tindakan tag-comboboxes) expose `.value` as an Array, which
        // would throw "(text||'').replace is not a function" here.
        const normalize = (text) => {
            if (typeof text !== 'string') text = (text === null || text === undefined) ? '' : String(text);
            return text.replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
        };
        // Read the human-visible answer from a candidate element.
        //  - Real form controls (INPUT/TEXTAREA/SELECT) hold the answer in
        //    `.value` (a string) — a date input is "2026-05-05", etc.
        //  - Custom SurveyJS widgets (combobox / tagbox / .sd-input DIVs) put an
        //    internal CODE in `.value` (a string "DSP7", or even an Array
        //    ["R73"] which used to crash normalize) and the readable selection
        //    in innerText ("Dewasa 0.5 Tablet; 3 kali…"). Prefer innerText for
        //    those so we capture the label the nakes actually sees.
        const elText = (el) => {
            if (!el) return '';
            const tag = el.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
                return (typeof el.value === 'string') ? el.value : '';
            }
            const inner = (el.innerText || '').trim();
            if (inner) return inner;
            return (typeof el.value === 'string') ? el.value : '';
        };
        const cleanQuestionLabel = (text) => {
            let label = normalize(text);
            label = label.replace(/^\\d+\\.\\s*/, '').trim();
            label = label.replace(/\\s*\\*\\s*$/, '').trim();
            return label;
        };
        const isInternalCode = (text) => /^PPV\\d+$/i.test(normalize(text));
        const isUselessDisplay = (text, questionLabel) => {
            const value = normalize(text);
            if (!value) return true;
            if (value === 'No data to display') return true;
            if (/^\\d+\\.?$/.test(value)) return true;
            if (isInternalCode(value)) return true;
            if (cleanQuestionLabel(value) === cleanQuestionLabel(questionLabel)) return true;
            return false;
        };
        const firstMeaningfulLine = (text) => {
            const lines = (text || '')
                .split('\\n')
                .map(line => normalize(line))
                .filter(Boolean);
            for (const line of lines) {
                if (/^\\d+\\.?$/.test(line)) continue;
                return line;
            }
            return '';
        };
        const extractChoiceText = (text, questionLabel) => {
            const lines = (text || '')
                .split('\\n')
                .map(line => normalize(line))
                .filter(Boolean);
            const cleanQuestion = cleanQuestionLabel(questionLabel);
            const candidates = lines.filter(line => {
                const cleanLine = cleanQuestionLabel(line);
                if (!cleanLine) return false;
                if (cleanLine === cleanQuestion) return false;
                if (cleanLine.startsWith(cleanQuestion) && cleanLine.length > cleanQuestion.length) return false;
                if (/^\\d+\\./.test(cleanLine)) return false;
                return true;
            });
            if (candidates.length === 0) return '';
            return candidates[candidates.length - 1];
        };
        const setAnswer = (label, answer) => {
            const cleanLabel = cleanQuestionLabel(label);
            if (!cleanLabel) return;
            if (Object.prototype.hasOwnProperty.call(result, cleanLabel) && result[cleanLabel] !== null) {
                // The label is already taken by a non-null answer. A blank repeat
                // is ignored; but a real repeated answer — e.g. a SurveyJS dynamic
                // panel like "Tambah resep obat" with several obat, each rendering
                // its own "Pilih obat"/"Dosis pemakaian" question — is kept under
                // an indexed key ("Pilih obat (2)", "(3)", …) so no entry is lost.
                // Questions render in panel order, so "Pilih obat (n)" pairs with
                // "Dosis pemakaian (n)".
                if (answer === null || answer === undefined || answer === '') return;
                let n = 2;
                while (Object.prototype.hasOwnProperty.call(result, cleanLabel + ' (' + n + ')')) n++;
                result[cleanLabel + ' (' + n + ')'] = answer;
                return;
            }
            result[cleanLabel] = answer ?? null;
        };

        // ── Strategy 0: SurveyJS-style forms used on form.kemkes.go.id ──
        const surveyQuestions = Array.from(
            document.querySelectorAll('.sd-question[data-name], .sd-question[id^="sq_"]')
        ).filter(el => el.offsetParent !== null);

        if (surveyQuestions.length > 0) {
            for (const question of surveyQuestions) {
                const titleEl = question.querySelector(
                    '.sd-question__title .sv-string-viewer, .sd-question__title'
                );
                // No data-name fallback: title-less SurveyJS elements in the real
                // CKG forms are display/expression panels (e.g. `education_display`,
                // `PROTA…-REK-…`) with no answer — keying them by data-name only
                // adds null-valued noise (verified live on DEVINA). Drop them.
                const questionLabel = cleanQuestionLabel(titleEl ? titleEl.innerText : '');
                if (!questionLabel) continue;

                let answer = null;
                const content = question.querySelector('.sd-question__content, .sd-element__content') || question;

                // SurveyJS boolean toggle: a single checkbox whose value may be an
                // explicit false (unchecked, NOT indeterminate) vs unanswered
                // (indeterminate). Handle it before the radio/checkbox readers so
                // an answered "false" is captured (not dropped) and an unanswered
                // one stays null. Scoped to `.sd-boolean`, so radiogroups are
                // unaffected. (Defensive: current CKG forms use Ya/Tidak
                // radiogroups, but this stops a future boolean from leaking the
                // raw "on" value or reading an explicit false as null.)
                const boolEl = content.querySelector('.sd-boolean');
                if (boolEl) {
                    const bcb = boolEl.querySelector('input[type="checkbox"]');
                    if (bcb) {
                        let bAnswer = null;
                        if (!bcb.indeterminate) {
                            const lblEl = boolEl.querySelector(
                                bcb.checked ? '.sd-boolean__label--true' : '.sd-boolean__label--false'
                            );
                            bAnswer = normalize(lblEl ? lblEl.innerText : '') || (bcb.checked ? 'Ya' : 'Tidak');
                        }
                        setAnswer(questionLabel, bAnswer);
                        continue;
                    }
                }

                const checkedRadio = content.querySelector('input[type="radio"]:checked');
                if (checkedRadio) {
                    const radioLabelEl =
                        checkedRadio.closest('label')?.querySelector('.sd-item__control-label, .sv-string-viewer') ||
                        checkedRadio.closest('label');
                    answer = normalize(radioLabelEl ? radioLabelEl.innerText : checkedRadio.value);
                }

                if (!answer) {
                    const checkedBoxes = Array.from(content.querySelectorAll('input[type="checkbox"]:checked'));
                if (checkedBoxes.length > 0) {
                        answer = checkedBoxes.map(cb => {
                            const labelEl =
                                cb.closest('label')?.querySelector('.sd-item__control-label, .sv-string-viewer') ||
                                cb.closest('label');
                            return normalize(labelEl ? labelEl.innerText : cb.value);
                        }).filter(Boolean).join(', ');
                    }
                }

                // SurveyJS "other"/"Lainnya" free text: when a selectbase option
                // reveals a comment input, append its typed value so the detail
                // isn't lost (we'd otherwise keep only the "Lainnya" label).
                if (answer) {
                    const otherInput = content.querySelector(
                        'input.sd-comment, textarea.sd-comment, .sd-selectbase__other input, ' +
                        '.sd-selectbase__other textarea, [class*="other"] input[type="text"], ' +
                        '[class*="other"] textarea'
                    );
                    if (otherInput && typeof otherInput.value === 'string') {
                        const otherText = normalize(otherInput.value);
                        if (otherText) answer = answer + ': ' + otherText;
                    }
                }

                // A selectbase question (radio/checkbox options) is answered
                // ONLY by its checked option(s). Nothing checked => genuinely
                // unanswered => null. Skip the label/dropdown/combobox readers
                // below, which would otherwise mis-read the FIRST option
                // (e.g. "Ya"/"Obat") as a phantom default — silently fabricating
                // an answer for an empty question.
                const isSelectBase = content.querySelector('input[type="radio"], input[type="checkbox"]') !== null;
                if (!answer && !isSelectBase) {
                    const displayCandidates = Array.from(
                        content.querySelectorAll(
                            '.sd-dropdown .sv-string-viewer, .sd-dropdown input:not([type="hidden"]), ' +
                            '[role="combobox"] .sv-string-viewer, [role="combobox"], ' +
                            '.sd-selectbase__label .sv-string-viewer, .sd-input'
                        )
                    );
                    for (const el of displayCandidates) {
                        const textValue = normalize(elText(el));
                        if (isUselessDisplay(textValue, questionLabel)) continue;
                        answer = textValue;
                        break;
                    }
                }

                if (!answer && !isSelectBase) {
                    const input = content.querySelector(
                        'input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"]), textarea'
                    );
                    if (input && input.value) {
                        const value = normalize(input.value);
                        if (!isInternalCode(value)) {
                            answer = value;
                        }
                    }
                }

                if (!answer && !isSelectBase) {
                    const select = content.querySelector('select');
                    if (select && select.selectedIndex >= 0) {
                        const value = normalize(select.options[select.selectedIndex].text || select.value);
                        if (!isInternalCode(value)) {
                            answer = value;
                        }
                    }
                }

                if (!answer && !isSelectBase) {
                    const candidateEls = Array.from(
                        content.querySelectorAll(
                            '.sd-input, .sd-dropdown input, .sd-dropdown .sv-string-viewer, [role="combobox"], .sv-string-viewer'
                        )
                    );
                    for (const el of candidateEls) {
                        const textValue = normalize(elText(el));
                        if (isUselessDisplay(textValue, questionLabel)) continue;
                        answer = textValue;
                        break;
                    }
                }

                setAnswer(questionLabel, answer);
            }
        }

        // ── Strategy 1: Find numbered questions (1. Question text *) ──
        // The forms use a pattern like:
        //   <div> 1. <strong>Question Text</strong> * </div>
        //   <div> radio/input/select </div>

        // Find all form question containers
        // Look for elements that start with a number followed by a dot
        const allEls = document.querySelectorAll('div, fieldset, section, [class*="question"], [class*="form-group"]');

        for (const container of allEls) {
            if (surveyQuestions.length > 0) break;
            // Check if this looks like a question container
            const rawText = container.innerText || '';
            const text = normalize(rawText);
            const match = text.match(/^(\\d+)\\.\\s*(.+)/);

            if (!match) continue;

            // The first visible line in the numbered card is the cleanest question text.
            let questionLabel = cleanQuestionLabel(firstMeaningfulLine(rawText));
            if (!questionLabel) continue;

            // Now find the answer within this container
            let answer = null;

            // Check for selected radio buttons
            const radios = container.querySelectorAll('input[type="radio"]');
            for (const radio of radios) {
                if (radio.checked) {
                    // Get the label text for this radio
                    const label = radio.closest('label') ||
                                  radio.parentElement?.querySelector('span, label, div');
                    if (label) {
                        answer = extractChoiceText(label.innerText, questionLabel) || normalize(label.innerText);
                    } else {
                        answer = normalize(radio.value);
                    }
                }
            }

            // Check for text/number inputs
            if (!answer) {
                const inputs = container.querySelectorAll(
                    'input[type="text"], input[type="number"], input[type="date"], textarea'
                );
                for (const input of inputs) {
                    if (input.value) {
                        answer = normalize(input.value);
                    }
                }
            }

            // Check for select dropdowns
            if (!answer) {
                const selects = container.querySelectorAll('select');
                for (const select of selects) {
                    if (select.value) {
                        const option = select.options[select.selectedIndex];
                        answer = normalize(option ? option.text : select.value);
                    }
                }
            }

            // Check for checked checkboxes
            if (!answer) {
                const checkboxes = container.querySelectorAll('input[type="checkbox"]');
                const checked = [];
                for (const cb of checkboxes) {
                    if (cb.checked) {
                        const label = cb.closest('label') ||
                                      cb.parentElement?.querySelector('span, label');
                        checked.push(normalize(label ? label.innerText : cb.value));
                    }
                }
                if (checked.length > 0) {
                    answer = checked.join(', ');
                }
            }

            // Check for visually selected radio buttons (custom styled, not native)
            if (!answer) {
                const customRadios = container.querySelectorAll(
                    '[class*="radio"], [class*="option"], [role="radio"]'
                );
                for (const radio of customRadios) {
                    const isChecked = radio.getAttribute('aria-checked') === 'true' ||
                                      radio.classList.toString().match(/checked|selected|active/i);
                    if (isChecked) {
                        const radioText = extractChoiceText(radio.innerText, questionLabel) || normalize(radio.innerText);
                        if (radioText && cleanQuestionLabel(radioText) !== questionLabel) {
                            answer = radioText;
                        }
                    }
                    // Also check for green/filled circle (custom radio indicator)
                    const circles = radio.querySelectorAll('div, span');
                    for (const circle of circles) {
                        const style = window.getComputedStyle(circle);
                        const bg = style.backgroundColor;
                        if ((bg.includes('45, 212') || bg.includes('20, 184') ||
                             bg.includes('34, 197') || bg.includes('13, 148')) &&
                            circle.offsetWidth < 30) {
                            const radioText = extractChoiceText(radio.innerText, questionLabel) || normalize(radio.innerText);
                            if (radioText && cleanQuestionLabel(radioText) !== questionLabel) {
                                answer = radioText;
                            }
                        }
                    }
                }
            }

            // Some forms show the chosen value inside a custom combobox/div.
            if (!answer) {
                const displays = container.querySelectorAll(
                    'input[readonly], [role="combobox"], [class*="select"], [class*="dropdown"]'
                );
                for (const display of displays) {
                    const rawValue = elText(display);
                    const textValue = extractChoiceText(rawValue, questionLabel) || normalize(rawValue);
                    if (!textValue) continue;
                    if (textValue === questionLabel) continue;
                    if (/^\\d+\\.$/.test(textValue)) continue;
                    answer = textValue;
                    break;
                }
            }

            if (questionLabel) {
                setAnswer(questionLabel, answer);
            }
        }

        // ── Strategy 2: Read React form state if available ──
        // Some React apps store form values in __reactFiber or __reactProps
        // This is a fallback — only used if Strategy 1 found nothing
        if (Object.keys(result).length === 0) {
            // Try reading all visible input values with their labels
            const inputs = document.querySelectorAll('input, select, textarea');
            for (const input of inputs) {
                if (!input.value && input.type !== 'radio') continue;
                if (input.type === 'radio' && !input.checked) continue;
                if (input.type === 'hidden') continue;

                // Find label
                let label = '';
                const labelEl = document.querySelector(`label[for="${input.id}"]`);
                if (labelEl) {
                    label = labelEl.innerText.trim();
                } else {
                    const closest = input.closest('label, [class*="form"], [class*="field"]');
                    if (closest) {
                        const texts = Array.from(closest.childNodes)
                            .filter(n => n.nodeType === Node.TEXT_NODE)
                            .map(n => n.textContent.trim())
                            .filter(t => t);
                        label = texts.join(' ') || input.name || input.id || '';
                    }
                }

                if (label) {
                    label = cleanQuestionLabel(label);
                    if (input.type === 'radio') {
                        const radioLabel = normalize(input.closest('label')?.innerText || input.value);
                        setAnswer(label, radioLabel);
                    } else {
                        setAnswer(label, normalize(input.value));
                    }
                }
            }
        }

        // ── Get the form title/heading ──
        const headings = document.querySelectorAll('h1, h2, h3');
        for (const h of headings) {
            const text = h.innerText ? h.innerText.trim() : '';
            if (text && text.length > 3 && !text.match(/^(Version|Version)/)) {
                result['_form_title'] = text;
                break;
            }
        }

        // Remove accidental duplicate keys where a longer polluted key contains
        // the same answer as a shorter clean key.
        const keys = Object.keys(result).filter(k => !k.startsWith('_'));
        for (const key of keys) {
            // Never drop an indexed repeat key ("Pilih obat (2)") — it would
            // otherwise be deleted as a "Pilih obat" prefix-dup when two panels
            // hold the same value (e.g. the same obat twice).
            if (/ \\(\\d+\\)$/.test(key)) continue;
            for (const other of keys) {
                if (key === other) continue;
                if (other.length >= key.length) continue;
                if (!key.startsWith(other)) continue;
                if (result[key] !== result[other]) continue;
                // `key` starts with `other` and shares its value. Only treat it
                // as a polluted duplicate (clean label + trailing answer/noise)
                // when what follows `other` is just the answer text or blank —
                // NOT a genuinely longer, distinct question. Without this guard,
                // "Apakah pasien dirujuk" would silently delete the real,
                // separate "Apakah pasien dirujuk ke FKTL" (same "Ya" value).
                const leftover = normalize(key.slice(other.length));
                const ansText = normalize(String(result[other] == null ? '' : result[other]));
                if (leftover === '' || leftover === ansText) {
                    delete result[key];
                }
            }
        }

        return result;
    }""")

    field_count = len([k for k in form_data if not k.startswith('_')])
    console.print(f"          Read {field_count} fields")

    return form_data or {}


# =============================================================================
# API-direct patient scraper (Phase 1+2)
#
# Instead of clicking "Mulai" (which navigates the list page away), this path
# calls POST /api/pkg/detail-screening directly with the patient's reg_id.
# That response already contains patient demographics + domicile + job + every
# form's URL, so we skip the detail-page render entirely and jump straight to
# opening form tabs.
#
# Forms are still read by opening their URL in new tabs (SurveyJS answers are
# only available in encrypted form via the API — see network reconnaissance).
# =============================================================================
def _fmt_id_date(iso: str | None) -> str:
    """`1976-04-17` → `17 April 1976`. Returns "" if the input is empty/bad."""
    if not iso:
        return ""
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except Exception:
        return iso
    return f"{d.day} {_ID_MONTHS[d.month]} {d.year}"


def _fmt_gender(g: str | None) -> str:
    """`PEREMPUAN` / `LAKI-LAKI` → `Perempuan` / `Laki-laki`."""
    if not g:
        return ""
    return g.strip().title()


def _fmt_mobile(m: str | None) -> str:
    """`6282110261647` → `+6282110261647`. Leave as-is if already prefixed."""
    if not m:
        return "-"
    m = m.strip()
    if not m:
        return "-"
    if m.startswith("+"):
        return m
    return "+" + m


def _compute_age_id(iso_dob: str | None, ref: date | None = None) -> str:
    """Indonesian age string: `50 Tahun 1 Hari` (or `Y Tahun M Bulan D Hari`)."""
    if not iso_dob:
        return ""
    try:
        dob = datetime.strptime(iso_dob[:10], "%Y-%m-%d").date()
    except Exception:
        return ""
    ref = ref or date.today()
    years = ref.year - dob.year
    months = ref.month - dob.month
    days = ref.day - dob.day
    if days < 0:
        months -= 1
        # days-in-previous-month
        prev_month = ref.month - 1 or 12
        prev_year = ref.year if ref.month > 1 else ref.year - 1
        import calendar
        days += calendar.monthrange(prev_year, prev_month)[1]
    if months < 0:
        years -= 1
        months += 12
    if months == 0 and days == 0:
        return f"{years} Tahun"
    if months == 0:
        return f"{years} Tahun {days} Hari"
    return f"{years} Tahun {months} Bulan {days} Hari"


def _format_detail_data_from_api(data: dict) -> dict:
    """Shape the /detail-screening JSON into the existing scraper output schema."""
    pd = data.get("patient_detail") or {}
    dom = data.get("domicile") or {}
    job = data.get("job") or pd.get("patient_job") or {}

    individu: dict = {}
    if pd.get("patient_nik"):
        individu["NIK"] = pd["patient_nik"]
    if pd.get("patient_born_date"):
        individu["Tanggal Lahir"] = _fmt_id_date(pd["patient_born_date"])
        age = _compute_age_id(pd["patient_born_date"])
        if age:
            individu["Umur"] = age
    if pd.get("patient_gender"):
        individu["Jenis Kelamin"] = _fmt_gender(pd["patient_gender"])
    # The existing dialog uses "Nama Ibu/Wali" = "-" when empty; preserve that.
    wali_name_for_individu = (pd.get("wali_full_name") or "").strip() or "-"
    individu["Nama Ibu/Wali"] = wali_name_for_individu
    if pd.get("ticket_number"):
        individu["Nomor Tiket"] = pd["ticket_number"]
    if pd.get("patient_full_name"):
        individu["Nama"] = pd["patient_full_name"].strip()
    if pd.get("patient_mobile_number"):
        individu["No. HP/WA orang tua"] = _fmt_mobile(pd["patient_mobile_number"])
    job_name = job.get("text") or job.get("name")
    if job_name:
        individu["Pekerjaan"] = job_name

    detail: dict = {"data_individu": individu}

    # Optional data_wali (only when a guardian is present)
    if (pd.get("wali_full_name") or "").strip():
        wali: dict = {}
        if pd.get("wali_nik"):
            wali["NIK"] = pd["wali_nik"]
        wali["Nama"] = pd["wali_full_name"].strip()
        if pd.get("wali_born_date"):
            wali["Tanggal Lahir"] = _fmt_id_date(pd["wali_born_date"])
        if pd.get("wali_gender"):
            wali["Jenis Kelamin"] = _fmt_gender(pd["wali_gender"])
        if pd.get("wali_mobile_number"):
            wali["No. HP"] = _fmt_mobile(pd["wali_mobile_number"])
        if wali:
            detail["data_wali"] = wali

    # data_domisili mirrors the dialog's keys (see knownLabels in
    # _read_detail_data_dialog: Alamat Domisili / Provinsi / Kota / ...).
    domisili: dict = {}
    if dom.get("address"):
        domisili["Alamat Domisili"] = dom["address"]
    if dom.get("province_name"):
        domisili["Provinsi"] = dom["province_name"]
    if dom.get("city_name"):
        domisili["Kota"] = dom["city_name"]
    if dom.get("district_name"):
        domisili["Kecamatan"] = dom["district_name"]
    if dom.get("sub_district_name"):
        domisili["Kelurahan"] = dom["sub_district_name"]
    if domisili:
        detail["data_domisili"] = domisili

    return detail


def get_mitra_token(context, base_url: str) -> str:
    """Call POST {base_url}/encrypt with an empty filter dict; return data_encrypt.

    The `mitra` field on /detail-screening is the encrypted form of the
    (empty) outer filter dialog. The result is stable for a session, so the
    caller is expected to cache it.
    """
    payload_inner = {
        "mitra_code": "",
        "kegiatan_code": "",
        "kategori_code": "",
        "sub_kategori_code": "",
        "location_province": "",
        "location_city": "",
        "location_district": "",
        "location_subdistrict": "",
        "location_detail": "",
        "paket_tag_code": "",
    }
    resp = context.request.post(
        f"{base_url}/encrypt",
        data=json.dumps({"data": json.dumps(payload_inner)}),
        headers={"Content-Type": "application/json"},
    )
    if resp.status in (401, 403):
        raise SessionExpiredError(f"/encrypt returned {resp.status} (session expired)")
    if not resp.ok:
        raise RuntimeError(f"/encrypt returned {resp.status}")
    body = resp.json()
    # `token_encrypt` is the AES ciphertext used as `mitra` on /detail-screening.
    # `data_encrypt` is just the plaintext echoed back.
    token = body.get("token_encrypt")
    if not token:
        raise RuntimeError(f"/encrypt response missing token_encrypt: {body}")
    return token


def fetch_detail_screening(context, base_url: str, *, faskes_code: str,
                           screening_date: str, reg_id: str, mitra: str) -> dict:
    """Call POST /api/pkg/detail-screening. Returns the `data` sub-object."""
    resp = context.request.post(
        f"{base_url}/api/pkg/detail-screening",
        data=json.dumps({
            "faskes_code": faskes_code,
            "screening_date": screening_date,
            "reg_id": reg_id,
            "mitra": mitra,
        }),
        headers={"Content-Type": "application/json"},
    )
    if resp.status in (401, 403):
        raise SessionExpiredError(
            f"/detail-screening {reg_id} returned {resp.status} (session expired)"
        )
    if not resp.ok:
        raise RuntimeError(f"/detail-screening {reg_id} returned {resp.status}")
    body = resp.json()
    return body.get("data") or {}


# =============================================================================
# Tatalaksana (follow-up treatment)
#
# When `detail-screening` reports `is_have_tatalaksana: true` (i.e. the patient
# finished pemeriksaan, so the detail page's top-right "Mulai Tatalaksana"
# button is clickable), the SPA navigates to /ckg-tatalaksana/detail and fires
# POST /api/pkg/tatalaksana/list-detail. That single response carries the whole
# Tatalaksana table — one row per (Kelompok Skrinning, klasifikasi) needing
# follow-up — with each row's status and the SurveyJS `form_link` behind the
# per-row "Mulai Tatalaksana" button.
#
# Status semantics (verified live, Pekayon Jaya 2026-06-15):
#   - "belum_dilakukan"  → the per-row form is BLANK (only today's date is
#                          pre-filled). The UI renders it as "Belum tatalaksana".
#                          We DO emit the table row but SKIP opening the form.
#   - any other status   → the tatalaksana was recorded; the row's form_link
#                          opens the same SurveyJS form with submitted answers
#                          applied (identical mechanism to Mandiri/Nakes forms),
#                          so we open it and read it via _read_all_form_fields.
# =============================================================================
# Raw `status` → human label as the UI renders it. Unknown values fall back to
# the raw string (so a future enum value still surfaces, just un-prettified).
_TATA_STATUS_LABELS = {
    "belum_dilakukan": "Belum tatalaksana",
}
# Statuses whose per-row form is empty → table row only, no form open.
_TATA_EMPTY_STATUSES = {"belum_dilakukan", ""}


def fetch_tatalaksana_detail(context, base_url: str, *, faskes_code: str,
                             reg_id: str, program_code: str = "pkg") -> dict:
    """Call POST /api/pkg/tatalaksana/list-detail. Returns the `data` sub-object.

    `faskes_code` + `reg_id` are the same values used for /detail-screening;
    `program_code` comes from the /detail-screening response (default "pkg").
    `find_one` stays empty — only `find_two` selects the patient.
    """
    resp = context.request.post(
        f"{base_url}/api/pkg/tatalaksana/list-detail",
        data=json.dumps({
            "find_one": {"faskes_code": "", "ta_lak_id": ""},
            "find_two": {
                "faskes_code": faskes_code,
                "reg_id": reg_id,
                "program_code": program_code or "pkg",
            },
        }),
        headers={"Content-Type": "application/json"},
    )
    if resp.status in (401, 403):
        raise SessionExpiredError(
            f"/tatalaksana/list-detail {reg_id} returned {resp.status} (session expired)"
        )
    if not resp.ok:
        raise RuntimeError(f"/tatalaksana/list-detail {reg_id} returned {resp.status}")
    body = resp.json()
    return body.get("data") or {}


def _compose_hasil_pemeriksaan(parameter: dict, tatalaksana_name: str | None) -> str | None:
    """Rebuild the "Hasil Pemeriksaan" cell, e.g. "3 Prediabetes (Prediabetes)".

    Composed from parameter.hasil.{nilai,klasifikasi} + the row's tatalaksana_name,
    mirroring how the Tatalaksana table renders it. Returns None if nothing usable.
    """
    hasil = (parameter or {}).get("hasil") or {}
    nilai = hasil.get("nilai")
    klasifikasi = hasil.get("klasifikasi")
    parts = []
    if nilai is not None and str(nilai) != "":
        parts.append(str(nilai))
    if klasifikasi:
        parts.append(str(klasifikasi))
    text = " ".join(parts)
    name = (tatalaksana_name or "").strip()
    if name:
        text = f"{text} ({name})".strip() if text else name
    return text or None


def _tata_row_needs_form(status: str | None, form_link: str | None,
                         is_submit_form: bool = False) -> bool:
    """True when the per-row "Mulai Tatalaksana" form holds data worth reading.

    Open the form when a ``form_link`` exists AND either:
      - ``status`` is anything other than "belum_dilakukan"/empty — covers the
        observed "selesai" plus any in-progress/unknown status we haven't seen
        (so a new enum still gets read rather than silently dropped), OR
      - ``is_submit_form`` is True — the authoritative "this form was submitted"
        flag from ``form_layanan``. Verified live (DEVINA, 2026-06-16):
        True↔selesai, False↔belum, so on real data this OR adds nothing; it is a
        belt-and-suspenders net for a *submitted* row that ever reports an
        empty/unknown status. It never opens a blank "belum_dilakukan" row
        (its flag is False), so there is no extra cost.
    """
    if not form_link:
        return False
    if is_submit_form:
        return True
    return (status or "").strip().lower() not in _TATA_EMPTY_STATUSES


def _format_tatalaksana_rows(data: dict) -> list[dict]:
    """Shape `tatalaksana[]` from list-detail into output rows (form_data unset).

    Dynamic over however many (Kelompok Skrinning × klasifikasi) rows exist.

    The curated keys below are a *convenience view* of what the UI renders. To
    stay lossless even if the API grows fields we did not anticipate, the entire
    untouched API row is kept under ``_raw`` — so nothing is silently dropped.
    """
    out_rows: list[dict] = []
    for r in data.get("tatalaksana") or []:
        parameter = r.get("parameter") or {}
        form_layanan = r.get("form_layanan") or {}
        status = r.get("status")
        out_rows.append({
            # "Kelompok Skrinning" group header (e.g. "Pemeriksaan Gula Darah Remaja")
            "kelompok_skrinning": r.get("hasil_pemeriksaan"),
            # row label under the group (e.g. "Prediabetes")
            "tatalaksana_name": r.get("tatalaksana_name"),
            # "Hasil Pemeriksaan" cell (composed) + raw components
            "hasil_pemeriksaan": _compose_hasil_pemeriksaan(parameter, r.get("tatalaksana_name")),
            "hasil_detail": parameter.get("hasil") or {},
            "parameter": {
                k: parameter.get(k)
                for k in ("code", "label", "name", "nilai_normal", "rekomendasi", "satuan")
                if parameter.get(k) not in (None, "")
            },
            # "Status" cell
            "status": status,
            "status_label": _TATA_STATUS_LABELS.get((status or "").strip().lower(), status),
            "tatalaksana_code": r.get("tatalaksana_code"),
            "hasil_pemeriksaan_code": r.get("hasil_pemeriksaan_code"),
            "form_code": form_layanan.get("form_code"),
            "form_name": form_layanan.get("form_name"),
            "is_submit_form": bool(form_layanan.get("is_submit_form")),
            # "Tatalaksana" cell — the per-row form. Filled below only when the
            # status is not "belum_dilakukan" (an empty form otherwise).
            "form_data": None,
            # Full untouched API row — lossless backstop for fields not curated
            # above (e.g. log_activity, form_layanan.*, any future column).
            "_raw": r,
        })
    return out_rows


def scrape_patient_tatalaksana(context, *, base_url: str, faskes_code: str,
                               reg_id: str, program_code: str = "pkg",
                               tab_pool: list | None = None) -> dict | None:
    """Fetch + shape the Tatalaksana table, reading per-row forms where present.

    Returns ``{"ta_lak_id", "klaster", "screening_date", "rows": [...]}`` or
    ``None`` when the patient has no tatalaksana rows. Reuses the caller's
    ``tab_pool`` so per-row form tabs share the patient's open pages.
    """
    data = fetch_tatalaksana_detail(
        context, base_url,
        faskes_code=faskes_code, reg_id=reg_id, program_code=program_code,
    )
    rows = _format_tatalaksana_rows(data)
    if not rows:
        return None

    # Build form-tab items only for rows that were actually filled in (status
    # past "belum_dilakukan" or flagged submitted) — a blank row is table-only.
    form_items = []
    for idx, raw in enumerate(data.get("tatalaksana") or []):
        form_layanan = raw.get("form_layanan") or {}
        link = form_layanan.get("form_link")
        if _tata_row_needs_form(raw.get("status"), link,
                                bool(form_layanan.get("is_submit_form"))):
            label = rows[idx].get("tatalaksana_name") or form_layanan.get("form_name") or rows[idx].get("kelompok_skrinning") or ""
            form_items.append({"layanan": label, "url": link, "has_answers": True, "_row_idx": idx})

    if form_items:
        console.print(f"      Tatalaksana: {len(form_items)} recorded form(s) → batch tabs")
        read = _batch_read_forms_via_tabs(
            context,
            [{k: v for k, v in it.items() if not k.startswith("_")} for it in form_items],
            tab_pool=tab_pool,
        )
        # _batch_read_forms_via_tabs returns results in input order, so this
        # positional zip is safe. Surface any per-form read error onto the row
        # so a transient failure isn't silently emitted as an empty form_data.
        for item, result in zip(form_items, read):
            idx = item["_row_idx"]
            rows[idx]["form_data"] = result.get("form_data") or {}
            if result.get("error"):
                rows[idx]["form_read_error"] = result["error"]

    return {
        "ta_lak_id": data.get("ta_lak_id"),
        "klaster": data.get("klaster"),
        "klaster_code": data.get("klaster_code"),
        "screening_date": data.get("screening_date"),
        "rows": rows,
        # Lossless backstop for every top-level list-detail field we did not
        # curate above (program_code, no_tiket, channel, screening_month/year,
        # detail_data_pasien, detail_faskes, …). Excludes the rows array, which
        # is already expanded (with its own per-row `_raw`) under "rows".
        "_raw_meta": {k: v for k, v in data.items() if k != "tatalaksana"},
    }


def scrape_patient_via_api(context, *, base_url: str, faskes_code: str,
                           screening_date: str, reg_id: str, mitra: str,
                           patient_label: str = "",
                           pelayanan_nakes_only: bool = False,
                           include_blank_forms: bool = False,
                           skip_forms: bool = False,
                           mandiri_only: bool = False,
                           scrape_tatalaksana: bool = True) -> dict:
    """Full per-patient scrape via API — no Mulai click, no detail page.

    Returns the same shape as `scrape_patient_detail`, plus an optional
    ``tatalaksana`` key when the patient has follow-up treatment data:
        {"detail_data": {...}, "pemeriksaan_mandiri": [...],
         "pelayanan_nakes": [...], "tatalaksana": {...}}

    Form answers are still read by opening form URLs in new tabs — the
    `FormResult` map in the API response is code-only and not usable without
    the schema (see Phase-0 reconnaissance).
    """
    console.print(f"\n    [bold]Patient (API): {patient_label or reg_id}[/bold]")

    data = fetch_detail_screening(
        context, base_url,
        faskes_code=faskes_code,
        screening_date=screening_date,
        reg_id=reg_id,
        mitra=mitra,
    )

    result = {
        "detail_data": _format_detail_data_from_api(data),
        "pemeriksaan_mandiri": [],
        "pelayanan_nakes": [],
    }

    # NIK-only mode: skip both Mandiri + Nakes form-tab opens (the dominant
    # cost). detail-screening already gave us NIK + Nama via the helper above.
    if skip_forms:
        return result

    # Shared tab pool across Mandiri + Nakes within this patient. Saves
    # ~67ms per form (new_page overhead) when both phases run. Closed at
    # end of patient.
    tab_pool: list = []

    try:
        # Pemeriksaan Mandiri: screening_forms. By default only IsSubmitForm=true
        # entries are collected; with include_blank_forms=true we also open
        # unsubmitted forms to read their question schema (answers will be blank).
        if pelayanan_nakes_only and not mandiri_only:
            console.print("      Mandiri: skipped (pelayanan_nakes_only=true)")
        else:
            mandiri_items = []
            for form in data.get("screening_forms") or []:
                is_submitted = bool(form.get("IsSubmitForm"))
                if not is_submitted and not include_blank_forms:
                    continue
                link = form.get("FormLink")
                name = form.get("FormName") or form.get("FormCode") or ""
                if link:
                    mandiri_items.append({"layanan": name, "url": link, "has_answers": is_submitted})
                else:
                    result["pemeriksaan_mandiri"].append({"layanan": name, "form_data": {}})

            if mandiri_items:
                console.print(f"      Mandiri: {len(mandiri_items)} forms → batch tabs")
                result["pemeriksaan_mandiri"].extend(
                    _batch_read_forms_via_tabs(context, mandiri_items, tab_pool=tab_pool)
                )

            # Completion signal for the backfill's has_mandiri flag: this run
            # actually attempted Mandiri, and it's COMPLETE only if no form
            # entry carries an `error` (tab open/read failure). A transient
            # failure leaves mandiri_complete=False so the patient is re-targeted
            # next run instead of being silently marked "done" with a hole.
            # An empty screening_forms (no Mandiri for this patient) is complete.
            result["mandiri_scraped"] = True
            result["mandiri_complete"] = not any(
                isinstance(e, dict) and e.get("error")
                for e in result["pemeriksaan_mandiri"]
            )

        # Mandiri-only backfill: Nakes + Tatalaksana already scraped — skip them
        # so we only re-open the (cheap) Mandiri forms. The ingestion patches the
        # existing blob rather than replacing it.
        if mandiri_only:
            return result

        # Pelayanan Nakes: screening_layanan[].list_pemeriksaan[]. By default
        # only IsSubmitForm=true AND NOT is_skip entries are collected (parity
        # with "Ya + Selesai diperiksa" DOM filter). With include_blank_forms=true
        # we also open skipped/unsubmitted entries to read their question schema.
        nakes_items = []
        for layanan in data.get("screening_layanan") or []:
            for pem in layanan.get("list_pemeriksaan") or []:
                is_submitted = bool(pem.get("IsSubmitForm"))
                is_skip = bool(pem.get("is_skip"))
                has_answers = is_submitted and not is_skip
                if not has_answers and not include_blank_forms:
                    continue
                link = pem.get("pemeriksaan_link")
                name = pem.get("pemeriksaan") or pem.get("pemeriksaan_code") or ""
                if link:
                    nakes_items.append({"layanan": name, "url": link, "has_answers": has_answers})
                else:
                    result["pelayanan_nakes"].append({"layanan": name, "form_data": {}})

        if nakes_items:
            console.print(f"      Nakes:   {len(nakes_items)} forms → batch tabs")
            result["pelayanan_nakes"].extend(
                _batch_read_forms_via_tabs(context, nakes_items, tab_pool=tab_pool)
            )

        # Tatalaksana (follow-up): only when detail-screening flags it (i.e. the
        # top-right "Mulai Tatalaksana" button is clickable). Independent of the
        # Mandiri/Nakes filters above — always collected when present unless
        # disabled. A tatalaksana fetch failure must not sink the whole patient,
        # so non-session errors are caught and recorded.
        if scrape_tatalaksana and data.get("is_have_tatalaksana"):
            try:
                tata = scrape_patient_tatalaksana(
                    context,
                    base_url=base_url,
                    faskes_code=faskes_code,
                    reg_id=reg_id,
                    program_code=data.get("program_code") or "pkg",
                    tab_pool=tab_pool,
                )
                if tata:
                    result["tatalaksana"] = tata
            except SessionExpiredError:
                raise
            except Exception as e:
                console.print(f"      [yellow]Tatalaksana read failed: {e}[/yellow]")
                result["tatalaksana"] = {"error": str(e)}
    finally:
        for tab in tab_pool:
            try:
                tab.close()
            except Exception:
                pass

    return result

