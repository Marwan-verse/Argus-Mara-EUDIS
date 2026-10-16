"""Human disposition of saved satellite review leads; no operational actions."""
import tkinter as tk
from tkinter import ttk
from uuid import uuid4

from argus.satellite_disposition import OUTCOMES


class EvidenceReview:
    def __init__(self, board, lead):
        self.board, self.lead = board, lead
        self.satellite = board.app.satellite
        self.client = board.app.soc_client
        self.workspace = self.satellite.workspace if self.client is None else None
        self.draft = None
        self.future = None
        self.window = tk.Toplevel(board.app.root)
        self.window.title('Review satellite / AIS evidence')
        self.window.geometry('620x590')
        self.window.transient(board.app.root)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=lead['title'], wraplength=570, font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(frame, text=f"Image {lead['acquired_utc']} · {lead['source_label']} pixels\n{lead['reason']}",
                  wraplength=570).pack(anchor='w', pady=8)
        scope = 'Shared host audit · authenticated SOC analyst' if self.client else 'Private workspace audit · Local analyst'
        ttk.Label(frame, text=scope+'\nAnalyst judgment; identity and intent remain unconfirmed.', wraplength=570).pack(anchor='w')
        previous = lead.get('analyst_review')
        text = ('Evidence changed since the last review. Review again.\n' if lead.get('evidence_changed') else '')
        if previous:
            text += f"Last: {OUTCOMES[previous['outcome']]} · {previous['actor']}\n{previous['saved_utc']}\n{previous['reason']}"
        if lead.get('review_error'):
            text += lead['review_error']
        history = tk.Text(frame, height=5, wrap='word')
        history.pack(fill='x', pady=8)
        history.insert('1.0', text or 'No analyst review saved yet.')
        history.configure(state='disabled')
        self.outcome = ttk.Combobox(frame, values=list(OUTCOMES.values()), state='readonly')
        self.outcome.current(0)
        self.outcome.pack(fill='x')
        ttk.Label(frame, text='Reason (8–2000 characters)').pack(anchor='w', pady=(8, 2))
        self.reason = tk.Text(frame, height=5, wrap='word')
        self.reason.pack(fill='both', expand=True)
        self.status = ttk.Label(frame, text='', wraplength=570)
        self.status.pack(fill='x', pady=6)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Open image evidence', command=lambda: board.open_evidence(lead)).pack(side='left')
        self.save_button = ttk.Button(buttons, text='Save analyst review', command=self.save)
        self.save_button.pack(side='right')

    def save(self):
        if self.future is not None:
            return
        if self.board.app.soc_client is not self.client:
            self.status.configure(text='SOC connection changed. Reopen the review in the current workspace.')
            return
        reason = self.reason.get('1.0', 'end').strip()
        if not 8 <= len(reason) <= 2000:
            self.status.configure(text='Write a reason of 8–2000 characters.')
            return
        outcome = next(k for k, v in OUTCOMES.items() if v == self.outcome.get())
        # An explicit unchanged retry uses the same immutable request identifier.
        if self.draft is None or (self.draft['outcome'], self.draft['reason']) != (outcome, reason):
            self.draft = {'event_id': str(uuid4()), 'lead_id': self.lead['id'],
                          'evidence_key': self.lead['evidence_key'], 'outcome': outcome, 'reason': reason}
        draft = dict(self.draft)
        def work():
            if self.client:
                return self.client.request('POST', '/v1/satellite/dispositions', draft)
            return self.workspace.save_disposition(draft, 'Local analyst')
        self.future = self.satellite.executor.submit(work)
        self.save_button.configure(state='disabled')
        self.reason.configure(state='disabled')
        self.outcome.configure(state='disabled')
        self.status.configure(text='Saving analyst judgment…')
        self.window.after(100, self.poll)

    def poll(self):
        if not self.future.done():
            self.window.after(100, self.poll)
            return
        try:
            result = self.future.result()
            if self.board.app.soc_client is self.client:
                self.board.refresh_evidence(result['comparisons'])
            self.window.destroy()
        except Exception as error:
            # Remote client errors already hide credentials and response bodies.
            message = str(error) if isinstance(error, (ValueError, OSError)) else 'Review save failed; check host access.'
            self.status.configure(text=message[:300]+' Your reason is retained for a manual retry.')
            self.future = None
            self.save_button.configure(state='normal')
            self.reason.configure(state='normal')
            self.outcome.configure(state='readonly')

    def close(self):
        if self.future is None:
            self.window.destroy()
        else:
            self.status.configure(text='Wait for the submitted review to finish saving.')
