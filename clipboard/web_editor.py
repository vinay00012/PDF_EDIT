"""
Visual Web UI for Direct PDF Text Editing
Fully optimized for Mobile (iOS & Android) and Desktop.
Ready for local use and cloud deployment (Vercel, Render, Railway).
"""

import os
import io
import json
import base64
import socket
import shutil
import tempfile
import traceback
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string
import pymupdf

from pdf_editor import (
    replace_exact_span,
    replace_text,
    int_to_rgb,
    rgb_to_hex,
    normalize_font_name,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64MB max

# Use OS tempdir so it works on Vercel (/tmp) and Local systems
UPLOAD_DIR = Path(tempfile.gettempdir()) / "pdf_editor_sessions"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SESSION = {
    "current_file": None,
    "original_file": None,
    "doc_name": None,
    "total_pages": 0,
    "undo_stack": [],
}


def get_local_ip() -> str:
    """Returns local LAN IP for mobile testing."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=4.0, user-scalable=yes, viewport-fit=cover">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="theme-color" content="#090d16">
    <title>PDF In-Place Editor</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #090d16;
            --bg-surface: #111827;
            --bg-elevated: #1e293b;
            --bg-card: rgba(30, 41, 59, 0.7);
            --border-subtle: #1f293d;
            --border-focus: #38bdf8;
            --primary: #38bdf8;
            --primary-hover: #0284c7;
            --primary-glow: rgba(56, 189, 248, 0.35);
            --success: #10b981;
            --danger: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --text-dim: #64748b;
            --safe-bottom: env(safe-area-inset-bottom, 0px);
            --safe-top: env(safe-area-inset-top, 0px);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            background-color: var(--bg-base);
            color: var(--text-main);
            height: 100vh;
            height: 100dvh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Top App Bar */
        .app-bar {
            background: rgba(17, 24, 39, 0.95);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border-subtle);
            padding: calc(8px + var(--safe-top)) 16px 8px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 30;
            flex-shrink: 0;
        }

        .brand-cluster {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
        }

        .brand-logo {
            background: linear-gradient(135deg, #0284c7, #38bdf8);
            color: white;
            font-size: 13px;
            font-weight: 700;
            padding: 6px 10px;
            border-radius: 8px;
            box-shadow: 0 2px 8px var(--primary-glow);
            flex-shrink: 0;
        }

        .doc-title-box {
            display: flex;
            flex-direction: column;
            min-width: 0;
        }

        .doc-name {
            font-size: 14px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 200px;
        }

        .doc-tag {
            font-size: 10px;
            color: var(--text-dim);
            letter-spacing: 0.3px;
            text-transform: uppercase;
        }

        .action-cluster {
            display: flex;
            align-items: center;
            gap: 6px;
            flex-shrink: 0;
        }

        .action-btn {
            background-color: var(--bg-elevated);
            color: var(--text-main);
            border: 1px solid var(--border-subtle);
            padding: 8px 12px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .action-btn:hover {
            border-color: var(--primary);
            color: var(--primary);
        }

        .action-btn.btn-undo {
            color: #38bdf8;
            border-color: rgba(56, 189, 248, 0.3);
        }

        .action-btn.btn-undo:hover {
            background: rgba(56, 189, 248, 0.15);
        }

        .action-btn.btn-primary {
            background: var(--primary);
            color: #090d16;
            font-weight: 600;
            border-color: var(--primary);
        }

        .action-btn.btn-success {
            background: var(--success);
            color: white;
            border-color: var(--success);
            font-weight: 600;
        }

        .action-btn:disabled {
            opacity: 0.35;
            cursor: not-allowed;
            pointer-events: none;
        }

        /* Workspace Main */
        .workspace {
            display: flex;
            flex: 1;
            overflow: hidden;
            position: relative;
        }

        /* Canvas Scroll Viewport */
        .viewport {
            flex: 1;
            overflow: auto;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 16px 12px calc(80px + var(--safe-bottom)) 12px;
            background: radial-gradient(circle at 50% 20%, #131b2e 0%, #090d16 100%);
            -webkit-overflow-scrolling: touch;
            position: relative;
        }

        /* Floating Bottom Controls (Mobile & Desktop) */
        .floating-bar {
            position: fixed;
            bottom: calc(16px + var(--safe-bottom));
            left: 50%;
            transform: translateX(-50%);
            background: rgba(17, 24, 39, 0.92);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(56, 189, 248, 0.2);
            padding: 6px 14px;
            border-radius: 40px;
            display: flex;
            align-items: center;
            gap: 12px;
            z-index: 25;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.6);
        }

        .page-counter {
            font-size: 13px;
            font-weight: 600;
            color: var(--text-main);
            min-width: 50px;
            text-align: center;
        }

        .icon-btn {
            background: rgba(255, 255, 255, 0.06);
            border: none;
            color: var(--text-main);
            width: 34px;
            height: 34px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .icon-btn:active {
            transform: scale(0.9);
            background: rgba(56, 189, 248, 0.2);
        }

        .icon-btn:disabled {
            opacity: 0.3;
            pointer-events: none;
        }

        .bar-divider {
            width: 1px;
            height: 20px;
            background: var(--border-subtle);
        }

        /* PDF Render Container */
        .pdf-wrap {
            position: relative;
            background: white;
            border-radius: 6px;
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.7);
            max-width: 100%;
            transform-origin: top center;
            transition: transform 0.15s ease-out;
            margin: 0 auto;
            user-select: none;
        }

        #page-image {
            display: block;
            max-width: 100%;
            height: auto;
            border-radius: 6px;
        }

        .text-layer {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: auto;
        }

        .text-hitbox {
            position: absolute;
            cursor: pointer;
            border-radius: 3px;
            transition: background-color 0.1s, border-color 0.1s;
        }

        /* Expanded touch hitbox for small screens */
        .text-hitbox::after {
            content: '';
            position: absolute;
            top: -6px;
            bottom: -6px;
            left: -4px;
            right: -4px;
        }

        .text-hitbox:hover, .text-hitbox:active {
            background: rgba(56, 189, 248, 0.25);
            outline: 1.5px solid var(--primary);
        }

        .text-hitbox.selected {
            background: rgba(56, 189, 248, 0.45);
            outline: 2px solid var(--primary);
            box-shadow: 0 0 12px var(--primary-glow);
        }

        /* Desktop Sidebar & Mobile Bottom Sheet Drawer */
        .sheet-drawer {
            width: 380px;
            background: var(--bg-surface);
            border-left: 1px solid var(--border-subtle);
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            z-index: 40;
            flex-shrink: 0;
        }

        .drawer-grabber {
            display: none;
            width: 44px;
            height: 5px;
            background: var(--border-subtle);
            border-radius: 4px;
            margin: 10px auto 4px auto;
        }

        .drawer-top-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 18px 8px 18px;
            border-bottom: 1px solid var(--border-subtle);
        }

        .drawer-title {
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.3px;
            color: var(--text-main);
        }

        .close-btn {
            background: none;
            border: none;
            color: var(--text-muted);
            font-size: 20px;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 6px;
        }

        .tab-nav {
            display: flex;
            border-bottom: 1px solid var(--border-subtle);
            background: rgba(0, 0, 0, 0.2);
        }

        .tab-link {
            flex: 1;
            padding: 12px;
            background: none;
            border: none;
            color: var(--text-dim);
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }

        .tab-link.active {
            color: var(--primary);
            border-bottom-color: var(--primary);
            background: rgba(56, 189, 248, 0.05);
        }

        .tab-pane {
            padding: 18px;
            display: none;
            flex-direction: column;
            gap: 16px;
        }

        .tab-pane.active {
            display: flex;
        }

        /* Typography Stats Card */
        .typography-badge-card {
            background: rgba(30, 41, 59, 0.4);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .badge-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
        }

        .badge-key {
            color: var(--text-dim);
        }

        .badge-val {
            font-weight: 600;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .color-dot {
            width: 14px;
            height: 14px;
            border-radius: 4px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            display: inline-block;
        }

        /* Inputs & Switches */
        .field-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .field-label {
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            letter-spacing: 0.2px;
        }

        .text-input, .text-area {
            background: var(--bg-base);
            border: 1px solid var(--border-subtle);
            border-radius: 10px;
            color: var(--text-main);
            padding: 12px 14px;
            font-size: 15px;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
            width: 100%;
        }

        .text-input:focus, .text-area:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.15);
        }

        .text-area {
            min-height: 75px;
            resize: vertical;
        }

        /* Modern iOS-style toggle switch */
        .switch-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 0;
            cursor: pointer;
        }

        .switch-label {
            font-size: 13px;
            color: var(--text-muted);
            font-weight: 500;
        }

        .switch-toggle {
            position: relative;
            width: 44px;
            height: 24px;
            background: var(--border-subtle);
            border-radius: 20px;
            transition: background 0.2s ease;
            flex-shrink: 0;
        }

        .switch-toggle::after {
            content: '';
            position: absolute;
            top: 2px;
            left: 2px;
            width: 20px;
            height: 20px;
            background: white;
            border-radius: 50%;
            transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        input[type="checkbox"]:checked + .switch-toggle {
            background: var(--primary);
        }

        input[type="checkbox"]:checked + .switch-toggle::after {
            transform: translateX(20px);
        }

        /* Action Buttons */
        .submit-btn {
            background: linear-gradient(135deg, #0284c7, #38bdf8);
            color: white;
            font-size: 15px;
            font-weight: 700;
            padding: 14px 20px;
            border-radius: 12px;
            border: none;
            cursor: pointer;
            box-shadow: 0 4px 16px var(--primary-glow);
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .submit-btn:active {
            transform: scale(0.98);
        }

        .cancel-btn {
            background: var(--bg-elevated);
            color: var(--text-muted);
            border: 1px solid var(--border-subtle);
            font-size: 14px;
            font-weight: 600;
            padding: 14px 18px;
            border-radius: 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            transition: all 0.2s ease;
        }

        .cancel-btn:hover {
            color: var(--text-main);
            border-color: var(--text-muted);
        }

        .cancel-btn:active {
            transform: scale(0.98);
        }

        /* Empty State */
        .empty-hero {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            padding: 40px 24px;
            border: 2px dashed rgba(56, 189, 248, 0.2);
            border-radius: 16px;
            margin: auto;
            max-width: 440px;
            background: rgba(17, 24, 39, 0.6);
            cursor: pointer;
            transition: all 0.2s;
        }

        .empty-hero:active {
            transform: scale(0.98);
            border-color: var(--primary);
        }

        .empty-glyph {
            font-size: 48px;
            margin-bottom: 12px;
        }

        .toast-pill {
            position: fixed;
            bottom: calc(80px + var(--safe-bottom));
            left: 50%;
            transform: translateX(-50%) translateY(50px);
            background: rgba(17, 24, 39, 0.95);
            border: 1px solid var(--primary);
            color: var(--text-main);
            padding: 10px 20px;
            border-radius: 30px;
            font-size: 13px;
            font-weight: 600;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
            z-index: 100;
            opacity: 0;
            pointer-events: none;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            white-space: nowrap;
        }

        .toast-pill.show {
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }

        /* Modal Dialog */
        .modal-shade {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            backdrop-filter: blur(8px);
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 100;
            padding: 20px;
        }

        .modal-dialog {
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 18px;
            padding: 24px;
            max-width: 400px;
            width: 100%;
            text-align: center;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.8);
        }

        /* ========================================================
           📱 MOBILE RESPONSIVE ADAPTATIONS (< 860px)
           ======================================================== */
        @media (max-width: 860px) {
            .app-bar {
                padding: calc(6px + var(--safe-top)) 12px 8px 12px;
            }

            .btn-text-full {
                display: none;
            }

            .action-btn {
                padding: 8px 10px;
            }

            .workspace {
                flex-direction: column;
            }

            .viewport {
                padding: 10px 6px calc(90px + var(--safe-bottom)) 6px;
            }

            /* Transform sidebar into a native-app Slide-Up Bottom Sheet */
            .sheet-drawer {
                position: fixed;
                bottom: 0;
                left: 0;
                width: 100%;
                max-height: 82vh;
                border-left: none;
                border-top: 1px solid rgba(56, 189, 248, 0.3);
                border-radius: 20px 20px 0 0;
                box-shadow: 0 -12px 35px rgba(0, 0, 0, 0.8);
                transform: translateY(105%);
                transition: transform 0.32s cubic-bezier(0.16, 1, 0.3, 1);
                padding-bottom: calc(16px + var(--safe-bottom));
                background: #111827;
            }

            .sheet-drawer.mobile-sheet-open {
                transform: translateY(0);
            }

            .drawer-grabber {
                display: block;
            }

            #placeholder-hint {
                display: none !important;
            }

            .floating-bar {
                bottom: calc(12px + var(--safe-bottom));
                gap: 8px;
                padding: 6px 12px;
            }
        }
    </style>
</head>
<body>

    <!-- Header / App Bar -->
    <header class="app-bar">
        <div class="brand-cluster">
            <span class="brand-logo">PDF EDIT</span>
            <div class="doc-title-box">
                <span class="doc-name" id="doc-title">Select a PDF</span>
                <span class="doc-tag" id="doc-status">Direct In-Place</span>
            </div>
        </div>

        <div class="action-cluster">
            <input type="file" id="file-picker" accept="application/pdf" style="display: none;">
            <button class="action-btn" onclick="document.getElementById('file-picker').click()" title="Open PDF">
                📁 <span class="btn-text-full">Open</span>
            </button>
            <button class="action-btn btn-undo" id="btn-undo" onclick="triggerUndo()" disabled title="Undo last step (Ctrl+Z)">
                ↩ <span class="btn-text-full">Undo</span>
            </button>
            <button class="action-btn" id="btn-find-drawer" onclick="openFindDrawer()" title="Find & Replace">
                🔍 <span class="btn-text-full">Search</span>
            </button>
            <button class="action-btn" id="btn-revert" onclick="revertDoc()" disabled title="Revert all changes">
                ↺ <span class="btn-text-full">Revert</span>
            </button>
            <button class="action-btn btn-success" id="btn-download" onclick="openDownloadModal()" disabled title="Download PDF with custom filename">
                ⬇ <span class="btn-text-full">Download</span>
            </button>
        </div>
    </header>

    <!-- Workspace -->
    <main class="workspace">
        
        <!-- Canvas Viewport -->
        <section class="viewport" id="viewport-area">
            
            <div id="empty-state-view" class="empty-hero" onclick="document.getElementById('file-picker').click()">
                <div class="empty-glyph">📄</div>
                <h3 style="font-size: 18px; font-weight: 700; margin-bottom: 6px;">Tap to Open PDF</h3>
                <p style="font-size: 13px; color: var(--text-muted); line-height: 1.4;">
                    Touch any word to replace it in-place.
                </p>
                <div style="margin-top: 16px; background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.2); padding: 6px 12px; border-radius: 20px; font-size: 12px; color: var(--primary);">
                    ✨ Auto-matches Font, Size, Weight & Color
                </div>
            </div>

            <div id="doc-render-area" style="display: none; width: 100%; display: flex; flex-direction: column; align-items: center;">
                <div class="pdf-wrap" id="pdf-wrapper">
                    <img id="page-image" alt="PDF Page Canvas">
                    <div class="text-layer" id="text-layer"></div>
                </div>
            </div>

            <!-- Floating Navigation & Zoom Bar -->
            <nav class="floating-bar" id="floating-bar" style="display: none;">
                <button class="icon-btn" onclick="prevPage()" id="prev-btn" title="Previous Page">←</button>
                <span class="page-counter" id="page-count-label">1 / 1</span>
                <button class="icon-btn" onclick="nextPage()" id="next-btn" title="Next Page">→</button>
                
                <div class="bar-divider"></div>
                
                <button class="icon-btn" onclick="adjustZoom(-0.15)" title="Zoom Out">−</button>
                <span id="zoom-indicator" style="font-size: 12px; font-weight: 600; min-width: 36px; text-align: center;">100%</span>
                <button class="icon-btn" onclick="adjustZoom(0.15)" title="Zoom In">+</button>
            </nav>

        </section>

        <!-- Sidebar (Desktop) / Slide-Up Sheet (Mobile) -->
        <aside class="sheet-drawer" id="sheet-drawer">
            <div class="drawer-grabber" onclick="cancelCurrentEdit()"></div>

            <div class="drawer-top-bar">
                <span class="drawer-title" id="drawer-heading">Edit Typography</span>
                <button class="close-btn" onclick="cancelCurrentEdit()">✕</button>
            </div>

            <nav class="tab-nav">
                <button class="tab-link active" id="tab-btn-edit" onclick="switchDrawerTab('edit')">Direct Edit</button>
                <button class="tab-link" id="tab-btn-find" onclick="switchDrawerTab('find')">Find & Replace</button>
            </nav>

            <!-- Tab 1: Direct Span Edit -->
            <div class="tab-pane active" id="pane-edit">
                <div id="inspector-form" style="display: none; flex-direction: column; gap: 14px;">
                    <div class="typography-badge-card">
                        <div class="badge-row">
                            <span class="badge-key">Font Family:</span>
                            <span class="badge-val" id="badge-font">-</span>
                        </div>
                        <div class="badge-row">
                            <span class="badge-key">Font Size:</span>
                            <span class="badge-val" id="badge-size">-</span>
                        </div>
                        <div class="badge-row">
                            <span class="badge-key">Color:</span>
                            <span class="badge-val">
                                <span class="color-dot" id="badge-color-dot"></span>
                                <span id="badge-color-hex">-</span>
                            </span>
                        </div>
                    </div>

                    <div class="field-group">
                        <label class="field-label">Original Text</label>
                        <textarea class="text-area" id="input-orig-text" readonly style="color: var(--text-dim); min-height: 48px;"></textarea>
                    </div>

                    <div class="field-group">
                        <label class="field-label">New Replacement Text</label>
                        <textarea class="text-area" id="input-new-text" placeholder="Type new text here..."></textarea>
                    </div>

                    <label class="switch-row">
                        <span class="switch-label">Auto-scale size if text overflows</span>
                        <input type="checkbox" id="check-auto-scale" checked style="display: none;">
                        <span class="switch-toggle"></span>
                    </label>

                    <!-- Cancel & Apply Action Buttons -->
                    <div style="display: flex; gap: 10px; margin-top: 6px;">
                        <button type="button" class="cancel-btn" onclick="cancelCurrentEdit()" style="flex: 1;">
                            ✕ Cancel
                        </button>
                        <button type="button" class="submit-btn" onclick="submitSpanEdit()" style="flex: 1.8;">
                            ✨ Apply
                        </button>
                    </div>
                </div>

                <div id="placeholder-hint" style="text-align: center; padding: 40px 10px; color: var(--text-dim); font-size: 13px;">
                    👉 Tap any word or line on the PDF canvas to edit it directly.
                </div>
            </div>

            <!-- Tab 2: Find & Replace -->
            <div class="tab-pane" id="pane-find">
                <div class="field-group">
                    <label class="field-label">Find Text</label>
                    <input type="text" class="text-input" id="input-find-query" placeholder="e.g. BOM">
                </div>

                <div class="field-group">
                    <label class="field-label">Replace With</label>
                    <input type="text" class="text-input" id="input-replace-query" placeholder="e.g. BOB">
                </div>

                <label class="switch-row">
                    <span class="switch-label">Apply across all pages</span>
                    <input type="checkbox" id="check-find-all" checked style="display: none;">
                    <span class="switch-toggle"></span>
                </label>

                <label class="switch-row">
                    <span class="switch-label">Auto-scale size if longer</span>
                    <input type="checkbox" id="check-find-scale" checked style="display: none;">
                    <span class="switch-toggle"></span>
                </label>

                <div style="display: flex; gap: 10px; margin-top: 8px;">
                    <button type="button" class="cancel-btn" onclick="closeDrawer()" style="flex: 1;">
                        ✕ Cancel
                    </button>
                    <button type="button" class="submit-btn" onclick="submitFindReplace()" style="flex: 1.8;">
                        🔍 Replace All
                    </button>
                </div>
            </div>

        </aside>

    </main>

    <!-- Download Naming Modal Dialog -->
    <div class="modal-shade" id="download-modal" onclick="closeDownloadModal(event)">
        <div class="modal-dialog" onclick="event.stopPropagation()">
            <div style="font-size: 36px; margin-bottom: 8px;">📥</div>
            <h3 style="font-size: 17px; font-weight: 700; margin-bottom: 6px;">Save Edited PDF</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 18px;">
                Choose a filename for your download:
            </p>
            
            <div class="field-group" style="text-align: left; margin-bottom: 20px;">
                <label class="field-label">Filename</label>
                <div style="position: relative; display: flex; align-items: center;">
                    <input type="text" class="text-input" id="download-filename-input" placeholder="my_edited_pdf" style="padding-right: 52px; font-weight: 600;">
                    <span style="position: absolute; right: 14px; font-size: 13px; font-weight: 700; color: var(--primary); pointer-events: none;">.pdf</span>
                </div>
            </div>

            <div style="display: flex; gap: 10px;">
                <button class="action-btn" onclick="closeDownloadModal()" style="flex: 1; justify-content: center; padding: 12px;">
                    Cancel
                </button>
                <button class="submit-btn" onclick="confirmDownload()" style="flex: 1.5; justify-content: center; margin: 0; padding: 12px;">
                    ⬇ Download
                </button>
            </div>
        </div>
    </div>

    <div class="toast-pill" id="toast-pill">Updated successfully!</div>

    <script>
        let currentPage = 1;
        let totalPages = 1;
        let activeSpan = null;
        let zoomScale = 1.0;
        let currentLoadedFilename = "";

        const filePicker = document.getElementById('file-picker');
        filePicker.addEventListener('change', (e) => {
            if (e.target.files.length > 0) uploadDocument(e.target.files[0]);
        });

        // Drag & drop support
        const viewportArea = document.getElementById('viewport-area');
        viewportArea.addEventListener('dragover', (e) => e.preventDefault());
        viewportArea.addEventListener('drop', (e) => {
            e.preventDefault();
            if (e.dataTransfer.files.length > 0) uploadDocument(e.dataTransfer.files[0]);
        });

        // Global Keyboard Shortcut: Ctrl+Z / Cmd+Z for Undo
        window.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
                const tag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
                if (tag !== 'input' && tag !== 'textarea') {
                    e.preventDefault();
                    triggerUndo();
                }
            } else if (e.key === 'Escape') {
                cancelCurrentEdit();
            }
        });

        window.addEventListener('DOMContentLoaded', async () => {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                if (data.active) {
                    totalPages = data.total_pages;
                    currentPage = 1;
                    currentLoadedFilename = data.filename || "";
                    document.getElementById('doc-title').innerText = data.filename;
                    updateUndoButton(data.can_undo);
                    showViewerLayout();
                    loadPage(currentPage);
                }
            } catch (e) {}
        });

        function showViewerLayout() {
            document.getElementById('empty-state-view').style.display = 'none';
            document.getElementById('doc-render-area').style.display = 'flex';
            document.getElementById('floating-bar').style.display = 'flex';
            document.getElementById('btn-download').disabled = false;
            document.getElementById('btn-revert').disabled = false;
        }

        function updateUndoButton(canUndo) {
            const btn = document.getElementById('btn-undo');
            btn.disabled = !canUndo;
        }

        async function uploadDocument(file) {
            const formData = new FormData();
            formData.append('pdf', file);

            popToast("Uploading PDF...");
            try {
                const res = await fetch('/api/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if (!res.ok || data.error) throw new Error(data.error || "Failed to upload");

                totalPages = data.total_pages;
                currentPage = 1;
                currentLoadedFilename = data.filename;
                document.getElementById('doc-title').innerText = data.filename;
                updateUndoButton(false);

                showViewerLayout();
                await loadPage(currentPage);
                popToast("PDF Loaded!");
            } catch (err) {
                alert("Upload failed: " + err.message);
            }
        }

        async function loadPage(pno) {
            try {
                const res = await fetch(`/api/page/${pno}`);
                const data = await res.json();
                if (!res.ok || data.error) throw new Error(data.error || "Failed to load page");

                document.getElementById('page-count-label').innerText = `${pno} / ${totalPages}`;
                document.getElementById('prev-btn').disabled = (pno <= 1);
                document.getElementById('next-btn').disabled = (pno >= totalPages);

                const img = document.getElementById('page-image');
                img.src = "data:image/png;base64," + data.image;

                img.onload = () => {
                    buildTextOverlay(data.spans, data.page_width, data.page_height, img.clientWidth, img.clientHeight);
                };
            } catch (err) {
                console.error(err);
            }
        }

        function buildTextOverlay(spans, origW, origH, renderedW, renderedH) {
            const layer = document.getElementById('text-layer');
            layer.innerHTML = '';

            const scaleX = renderedW / origW;
            const scaleY = renderedH / origH;

            spans.forEach((span) => {
                const box = document.createElement('div');
                box.className = 'text-hitbox';
                const bbox = span.bbox;

                box.style.left = `${bbox[0] * scaleX}px`;
                box.style.top = `${bbox[1] * scaleY}px`;
                box.style.width = `${(bbox[2] - bbox[0]) * scaleX}px`;
                box.style.height = `${(bbox[3] - bbox[1]) * scaleY}px`;
                box.title = `${span.text} (${span.font}, ${span.size}pt)`;

                box.onclick = (e) => {
                    e.stopPropagation();
                    if (navigator.vibrate) navigator.vibrate(12);
                    pickSpan(span, box);
                };

                layer.appendChild(box);
            });
        }

        function pickSpan(span, el) {
            document.querySelectorAll('.text-hitbox').forEach(b => b.classList.remove('selected'));
            if (el) el.classList.add('selected');

            activeSpan = span;
            document.getElementById('placeholder-hint').style.display = 'none';
            document.getElementById('inspector-form').style.display = 'flex';

            document.getElementById('badge-font').innerText = span.font;
            document.getElementById('badge-size').innerText = `${span.size} pt`;
            document.getElementById('badge-color-hex').innerText = span.color_hex;
            document.getElementById('badge-color-dot').style.backgroundColor = span.color_hex;

            document.getElementById('input-orig-text').value = span.text;
            document.getElementById('input-new-text').value = span.text;

            const drawer = document.getElementById('sheet-drawer');
            drawer.classList.add('mobile-sheet-open');

            switchDrawerTab('edit');

            setTimeout(() => {
                document.getElementById('input-new-text').focus();
            }, 300);
        }

        /* Cancel current edit: closes drawer and restores full view */
        function cancelCurrentEdit() {
            activeSpan = null;
            document.querySelectorAll('.text-hitbox').forEach(b => b.classList.remove('selected'));
            document.getElementById('inspector-form').style.display = 'none';
            document.getElementById('placeholder-hint').style.display = 'block';
            closeDrawer();
            popToast("Edit cancelled");
        }

        function closeDrawer() {
            document.getElementById('sheet-drawer').classList.remove('mobile-sheet-open');
        }

        function openFindDrawer() {
            switchDrawerTab('find');
            document.getElementById('sheet-drawer').classList.add('mobile-sheet-open');
        }

        async function submitSpanEdit() {
            if (!activeSpan) return;
            const newText = document.getElementById('input-new-text').value;
            const autoScale = document.getElementById('check-auto-scale').checked;

            popToast("Applying replacement...");
            try {
                const res = await fetch('/api/replace_span', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        page: currentPage,
                        span: activeSpan,
                        new_text: newText,
                        auto_shrink: autoScale
                    })
                });

                const data = await res.json().catch(() => null);
                if (!res.ok || (data && data.error)) {
                    throw new Error((data && data.error) || "Replacement failed");
                }

                updateUndoButton(true);
                popToast("Replaced in-place!");
                await loadPage(currentPage);
                document.getElementById('placeholder-hint').style.display = 'block';
                document.getElementById('inspector-form').style.display = 'none';
                activeSpan = null;
                closeDrawer();
            } catch (err) {
                alert("Error: " + err.message);
            }
        }

        async function submitFindReplace() {
            const findStr = document.getElementById('input-find-query').value;
            const replaceStr = document.getElementById('input-replace-query').value;
            const allPages = document.getElementById('check-find-all').checked;
            const autoScale = document.getElementById('check-find-scale').checked;

            if (!findStr) {
                alert("Please enter text to find.");
                return;
            }

            popToast("Replacing...");
            try {
                const res = await fetch('/api/find_replace', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        find: findStr,
                        replace: replaceStr,
                        page: allPages ? null : currentPage,
                        auto_shrink: autoScale
                    })
                });

                const data = await res.json().catch(() => null);
                if (!res.ok || (data && data.error)) {
                    throw new Error((data && data.error) || "Find and replace failed");
                }

                updateUndoButton(true);
                popToast(`Replaced ${data.count} occurrence(s)!`);
                loadPage(currentPage);
                closeDrawer();
            } catch (err) {
                alert("Error: " + err.message);
            }
        }

        /* ========================================================
           ↩ SINGLE STEP-BY-STEP UNDO LOGIC
           ======================================================== */
        async function triggerUndo() {
            popToast("Undoing last step...");
            try {
                const res = await fetch('/api/undo', { method: 'POST' });
                const data = await res.json();
                if (!res.ok || data.error) throw new Error(data.error || "Nothing to undo");

                updateUndoButton(data.can_undo);
                popToast("Undone 1 step back!");
                await loadPage(currentPage);
                
                // Reset inspector if open
                cancelCurrentEdit();
            } catch (err) {
                alert("Undo: " + err.message);
            }
        }

        function adjustZoom(delta) {
            zoomScale = Math.max(0.6, Math.min(2.5, zoomScale + delta));
            const wrap = document.getElementById('pdf-wrapper');
            wrap.style.transform = `scale(${zoomScale})`;
            document.getElementById('zoom-indicator').innerText = `${Math.round(zoomScale * 100)}%`;
        }

        function prevPage() {
            if (currentPage > 1) {
                currentPage--;
                loadPage(currentPage);
            }
        }

        function nextPage() {
            if (currentPage < totalPages) {
                currentPage++;
                loadPage(currentPage);
            }
        }

        function switchDrawerTab(tabId) {
            document.querySelectorAll('.tab-link').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(c => c.classList.remove('active'));

            if (tabId === 'edit') {
                document.getElementById('tab-btn-edit').classList.add('active');
                document.getElementById('pane-edit').classList.add('active');
                document.getElementById('drawer-heading').innerText = "Edit Typography";
            } else {
                document.getElementById('tab-btn-find').classList.add('active');
                document.getElementById('pane-find').classList.add('active');
                document.getElementById('drawer-heading').innerText = "Find & Replace";
            }
        }

        /* ========================================================
           📥 CUSTOM DOWNLOAD FILENAME LOGIC
           ======================================================== */
        function openDownloadModal() {
            const input = document.getElementById('download-filename-input');
            let base = currentLoadedFilename || document.getElementById('doc-title').innerText || "document";
            base = base.replace(/\\.pdf$/i, "");
            if (!base.startsWith("edited_")) {
                base = "edited_" + base;
            }
            input.value = base;
            document.getElementById('download-modal').style.display = 'flex';
            setTimeout(() => {
                input.focus();
                input.select();
            }, 100);
        }

        function closeDownloadModal(e) {
            document.getElementById('download-modal').style.display = 'none';
        }

        function confirmDownload() {
            let name = document.getElementById('download-filename-input').value.trim();
            if (!name) name = "edited_document";
            if (!name.toLowerCase().endsWith(".pdf")) {
                name += ".pdf";
            }
            closeDownloadModal();
            popToast(`Downloading ${name}...`);
            window.location.href = `/api/download?filename=${encodeURIComponent(name)}`;
        }

        document.getElementById('download-filename-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                confirmDownload();
            }
        });

        async function revertDoc() {
            if (!confirm("Revert document back to the original state?")) return;
            const res = await fetch('/api/revert', { method: 'POST' });
            await res.json();
            updateUndoButton(false);
            popToast("Reverted to original!");
            loadPage(currentPage);
        }

        function popToast(msg) {
            const t = document.getElementById('toast-pill');
            t.innerText = msg;
            t.classList.add('show');
            setTimeout(() => t.classList.remove('show'), 2400);
        }
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/status")
def api_status():
    if SESSION.get("current_file") and os.path.exists(SESSION["current_file"]):
        return jsonify({
            "active": True,
            "filename": SESSION.get("doc_name"),
            "total_pages": SESSION.get("total_pages", 1),
            "can_undo": len(SESSION.get("undo_stack", [])) > 0,
            "local_ip": get_local_ip(),
        })
    return jsonify({"active": False, "can_undo": False, "local_ip": get_local_ip()})


@app.route("/api/upload", methods=["POST"])
def upload_pdf():
    try:
        if "pdf" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        file = request.files["pdf"]
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        filename = Path(file.filename).name
        save_path = UPLOAD_DIR / f"current_{filename}"
        orig_path = UPLOAD_DIR / f"orig_{filename}"

        file.save(save_path)
        shutil.copyfile(save_path, orig_path)

        doc = pymupdf.open(str(save_path))
        total_pages = len(doc)
        doc.close()

        SESSION["current_file"] = str(save_path.resolve())
        SESSION["original_file"] = str(orig_path.resolve())
        SESSION["doc_name"] = filename
        SESSION["total_pages"] = total_pages
        SESSION["undo_stack"] = []

        return jsonify({"filename": filename, "total_pages": total_pages})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/page/<int:pno>")
def get_page(pno):
    if not SESSION["current_file"] or not os.path.exists(SESSION["current_file"]):
        return jsonify({"error": "No document active"}), 400

    try:
        doc = pymupdf.open(SESSION["current_file"])
        if pno < 1 or pno > len(doc):
            doc.close()
            return jsonify({"error": "Page out of range"}), 400

        page = doc[pno - 1]
        rect = page.rect
        width, height = rect.width, rect.height

        # Render image at 150 DPI for crisp visual presentation
        pix = page.get_pixmap(dpi=150)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")

        # Extract all text spans with metadata
        blocks = page.get_text("dict")["blocks"]
        spans = []

        for b in blocks:
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    txt = s["text"].strip()
                    if not txt:
                        continue
                    color_rgb = int_to_rgb(s["color"])
                    color_hex = rgb_to_hex(*color_rgb)
                    spans.append({
                        "text": s["text"],
                        "font": s["font"],
                        "size": round(s["size"], 1),
                        "color": s["color"],
                        "color_hex": color_hex,
                        "flags": s.get("flags", 0),
                        "bbox": [round(v, 1) for v in s["bbox"]],
                        "origin": [round(v, 1) for v in s["origin"]],
                    })

        doc.close()
        return jsonify({
            "page_width": width,
            "page_height": height,
            "image": img_b64,
            "spans": spans,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/replace_span", methods=["POST"])
def api_replace_span():
    try:
        data = request.json or {}
        pno = data.get("page", 1)
        span = data.get("span")
        new_text = data.get("new_text", "")
        auto_shrink = data.get("auto_shrink", False)

        if not SESSION["current_file"] or not span:
            return jsonify({"error": "Invalid request parameters"}), 400

        # Snapshot current PDF state to undo stack before applying edit
        with open(SESSION["current_file"], "rb") as f:
            SESSION["undo_stack"].append(f.read())
        if len(SESSION["undo_stack"]) > 25:
            SESSION["undo_stack"].pop(0)

        doc = pymupdf.open(SESSION["current_file"])
        page = doc[pno - 1]

        replace_exact_span(
            page=page,
            bbox=tuple(span["bbox"]),
            origin=tuple(span["origin"]),
            font_name=span["font"],
            font_size=span["size"],
            color_val=span["color"],
            flags=span.get("flags", 0),
            new_text=new_text,
            auto_shrink=auto_shrink,
        )

        pdf_bytes = doc.tobytes(deflate=True, garbage=3)
        doc.close()

        with open(SESSION["current_file"], "wb") as f:
            f.write(pdf_bytes)

        return jsonify({"success": True, "can_undo": len(SESSION["undo_stack"]) > 0})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/find_replace", methods=["POST"])
def api_find_replace():
    try:
        data = request.json or {}
        find_str = data.get("find")
        replace_str = data.get("replace", "")
        pno = data.get("page")
        auto_shrink = data.get("auto_shrink", False)

        if not SESSION["current_file"] or not find_str:
            return jsonify({"error": "Missing parameters"}), 400

        # Snapshot current PDF state to undo stack before applying edit
        with open(SESSION["current_file"], "rb") as f:
            SESSION["undo_stack"].append(f.read())
        if len(SESSION["undo_stack"]) > 25:
            SESSION["undo_stack"].pop(0)

        count = replace_text(
            input_path=SESSION["current_file"],
            output_path=SESSION["current_file"],
            find_str=find_str,
            replace_str=replace_str,
            page_num=pno,
            auto_shrink=auto_shrink,
        )

        return jsonify({"success": True, "count": count, "can_undo": len(SESSION["undo_stack"]) > 0})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/undo", methods=["POST"])
def api_undo():
    try:
        if not SESSION.get("current_file") or not SESSION.get("undo_stack"):
            return jsonify({"error": "No more undo steps available"}), 400

        prev_bytes = SESSION["undo_stack"].pop()
        with open(SESSION["current_file"], "wb") as f:
            f.write(prev_bytes)

        can_undo = len(SESSION["undo_stack"]) > 0
        return jsonify({"success": True, "can_undo": can_undo})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/download")
def download_file():
    if not SESSION["current_file"] or not os.path.exists(SESSION["current_file"]):
        return "No file available", 404

    # Custom filename requested by user
    custom_name = request.args.get("filename", "").strip()
    if not custom_name:
        custom_name = f"edited_{SESSION['doc_name'] or 'document.pdf'}"
    if not custom_name.lower().endswith(".pdf"):
        custom_name += ".pdf"

    return send_file(
        SESSION["current_file"],
        as_attachment=True,
        download_name=custom_name,
    )


@app.route("/api/revert", methods=["POST"])
def revert_file():
    if not SESSION["original_file"] or not os.path.exists(SESSION["original_file"]):
        return jsonify({"error": "No backup found"}), 400
    shutil.copyfile(SESSION["original_file"], SESSION["current_file"])
    SESSION["undo_stack"] = []
    return jsonify({"success": True})


if __name__ == "__main__":
    local_ip = get_local_ip()
    port = 5000
    print("\n" + "=" * 55)
    print("  🚀 PDF Direct In-Place Editor is running!")
    print(f"  💻 On this PC:    http://127.0.0.1:{port}")
    print(f"  📱 On your Phone:  http://{local_ip}:{port}")
    print("=" * 55 + "\n")
    app.run(host="0.0.0.0", port=port, debug=False)
