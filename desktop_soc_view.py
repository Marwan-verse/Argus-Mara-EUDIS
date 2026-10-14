"""Guided native SOC workspace: connect, verify peers, then communicate."""
import time
import tkinter as tk

import customtkinter as ctk

BG, CARD, CONTROL = '#0b1118', '#141e28', '#1c2a36'
INK, MUTED, ACCENT, LINE = '#e4ebf0', '#a8b6c2', '#47c7da', '#2c3d4c'


def label(parent, text='', size=13, bold=False, **kwargs):
    return ctk.CTkLabel(parent, text=text, text_color=kwargs.pop('text_color', INK),
                       font=kwargs.pop('font', ctk.CTkFont('Segoe UI', size, 'bold' if bold else 'normal')), **kwargs)


def button(parent, text, command, primary=False, **kwargs):
    return ctk.CTkButton(parent, text=text, command=command, height=36, corner_radius=7,
                        fg_color=ACCENT if primary else CONTROL,
                        text_color=BG if primary else INK, hover_color='#6ed5e3' if primary else '#283a4a', **kwargs)


def build(soc):
    soc.window = ctk.CTkToplevel(soc.app.root)
    soc.window.title('Argus Mara · Team communication')
    soc.window.geometry('1040x740')
    soc.window.minsize(920, 660)
    soc.window.configure(fg_color=BG)
    soc.window.transient(soc.app.root)
    header = ctk.CTkFrame(soc.window, fg_color='transparent')
    header.pack(fill='x', padx=22, pady=(18, 4))
    label(header, 'Team communication', 23, True).pack(side='left')
    soc.sign_out_button = button(header, 'Sign out', soc.sign_out, width=96)
    soc.sign_out_button.pack(side='right', padx=(12, 0))
    label(header, soc.client.user['username'], text_color=MUTED).pack(side='right')
    soc.tabs = ctk.CTkTabview(soc.window, fg_color=BG, segmented_button_selected_color=CONTROL,
                             segmented_button_selected_hover_color=CONTROL)
    soc.tabs.pack(fill='both', expand=True, padx=14, pady=(0, 10))
    frame = soc.tabs.add('Team room')
    frame.grid_columnconfigure(1, weight=1)
    frame.grid_rowconfigure(0, weight=1)
    left = ctk.CTkScrollableFrame(frame, width=274, fg_color=CARD, corner_radius=10)
    left.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
    label(left, '1  Connect with your team', 16, True).pack(anchor='w', padx=12, pady=(12, 8))
    soc.connect_controls = ctk.CTkFrame(left, fg_color='transparent')
    soc.connect_controls.pack(fill='x', padx=12)
    soc.group = tk.StringVar(value='Team session (all groups)')
    choices = ['Team session (all groups)'] + ['Private: ' + g for g in soc.client.user['groups']]
    soc.group_selector_session = ctk.CTkOptionMenu(soc.connect_controls, variable=soc.group, values=choices,
                                                  command=lambda _: scope_hint(soc), height=34)
    soc.group_selector_session.pack(fill='x')
    soc.scope_label = label(soc.connect_controls, '', wraplength=245, justify='left', text_color=MUTED)
    soc.scope_label.pack(fill='x', pady=(7, 9))
    soc.create_button = button(soc.connect_controls, 'Create a session', soc.create, True)
    soc.create_button.pack(fill='x')
    label(soc.connect_controls, 'or join a teammate', text_color=MUTED).pack(pady=10)
    soc.join_code = ctk.CTkEntry(soc.connect_controls, placeholder_text='Session code · ABCD-EFGH', height=36)
    soc.join_code.pack(fill='x')
    soc.join_code.bind('<Return>', lambda _: soc.join(soc.join_code.get()))
    soc.join_button = button(soc.connect_controls, 'Join session', lambda: soc.join(soc.join_code.get()))
    soc.join_button.pack(fill='x', pady=(7, 12))
    soc.invite_card = ctk.CTkFrame(left, fg_color=CONTROL, corner_radius=8)
    soc.invite_card.pack(fill='x', padx=12, pady=6)
    label(soc.invite_card, 'Share this invitation', text_color=MUTED).pack(pady=(10, 0))
    soc.invite_label = label(soc.invite_card, '', 25, True, font=ctk.CTkFont('Consolas', 25, 'bold'))
    soc.invite_label.pack(pady=4)
    soc.invite_expiry = label(soc.invite_card, '', text_color=MUTED)
    soc.invite_expiry.pack()
    soc.copy_button = button(soc.invite_card, 'Copy invite', soc.copy_invite)
    soc.copy_button.pack(fill='x', padx=12, pady=10)
    soc.participants_caption = label(left, 'Participants', 15, True)
    soc.participants_caption.pack(anchor='w', padx=12, pady=(15, 6))
    soc.participants_frame = ctk.CTkFrame(left, fg_color='transparent')
    soc.participants_frame.pack(fill='x', padx=12)
    soc.start_button = button(left, 'Start secure chat', lambda: soc.task(soc.client.lock, soc.reset), True)
    soc.start_button.pack(fill='x', padx=12, pady=10)
    soc.confirm_button = button(left, 'Confirm verification', lambda: soc.task(soc.client.confirm, soc.confirmed))
    soc.confirm_button.pack(fill='x', padx=12, pady=4)
    soc.leave_button = button(left, 'Leave session', soc.leave)
    soc.leave_button.pack(fill='x', padx=12, pady=(6, 12))
    right = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=10)
    right.grid(row=0, column=1, sticky='nsew')
    top = ctk.CTkFrame(right, fg_color='transparent')
    top.pack(fill='x', padx=20, pady=(16, 6))
    soc.stage_label = label(top, '', 18, True)
    soc.stage_label.pack(anchor='w')
    soc.safety_label = label(top, '', text_color=MUTED, width=1, wraplength=420, justify='left', anchor='w')
    soc.safety_label.pack(fill='x', pady=(4, 8))
    soc.status_label = label(top, soc.last_status, width=1, wraplength=420, justify='left', anchor='w', text_color=ACCENT)
    soc.status_label.pack(fill='x')
    soc.tools_label = label(top, '', 12, width=1, text_color=MUTED, wraplength=420, justify='left', anchor='w')
    soc.tools_label.pack(fill='x', pady=(5, 0))
    soc.chat = ctk.CTkTextbox(right, state='disabled', wrap='word', fg_color=BG,
                             text_color=INK, font=('Segoe UI', 13), corner_radius=8)
    soc.chat.pack(fill='both', expand=True, padx=16, pady=12)
    sharing = ctk.CTkFrame(right, fg_color='transparent')
    sharing.pack(fill='x', padx=16, pady=(0, 6))
    soc.contact_button = button(sharing, 'Share selected contact', soc.share_contact, width=172)
    soc.contact_button.pack(side='left', padx=(0, 6))
    soc.evidence_button = button(sharing, 'Share evidence', soc.share_evidence, width=130)
    soc.evidence_button.pack(side='left')
    compose = ctk.CTkFrame(right, fg_color=CONTROL, corner_radius=8)
    compose.pack(fill='x', padx=16, pady=(0, 5))
    soc.message = ctk.CTkTextbox(compose, height=70, wrap='word', fg_color=CONTROL,
                                font=('Segoe UI', 13), border_width=0)
    soc.message.pack(side='left', fill='both', expand=True, padx=8, pady=6)
    soc.message.bind('<Return>', soc.enter_message)
    soc.send_button = button(compose, 'Send', soc.send_text, True, width=78)
    soc.send_button.pack(side='right', padx=10)
    footer = label(right, 'Enter to send · Shift+Enter for a new line · Pings share after verification',
                   11, width=1, text_color=MUTED, wraplength=420, anchor='w', justify='left')
    footer.pack(fill='x', padx=18, pady=(0, 10))
    def resize(_=None):
        width = max(230, int(right.winfo_width() / ctk.ScalingTracker.get_widget_scaling(right)) - 44)
        for control in (soc.safety_label, soc.status_label, soc.tools_label, footer):
            control.configure(wraplength=width)
    right.bind('<Configure>', resize)
    soc.kind = tk.StringVar(value='chat')
    soc._participants_signature = None
    soc._chat_signature = None
    scope_hint(soc)
    if soc.client.user['admin']:
        admin = soc.tabs.add('Administration')
        scroll = ctk.CTkScrollableFrame(admin, fg_color=CARD)
        scroll.pack(fill='both', expand=True)
        soc.build_admin(scroll)


def scope_hint(soc):
    team = soc.group.get() == 'Team session (all groups)'
    soc.scope_label.configure(text='Invite people from any group. Shared tools follow everyone’s access.' if team else 'Only members of this group can join.')


def render(soc):
    if not soc.window or not soc.window.winfo_exists():
        return
    room, cipher = soc.client.room, soc.client.cipher
    members = (room or {}).get('members', [])
    locked = bool(room and room.get('locked'))
    ready = bool(locked and cipher and cipher.verified and len(room['confirmed']) == len(members) and soc.app.soc_online)
    own_id = soc.client.user['id']
    host = bool(room and room.get('host_id') == own_id)
    if room:
        soc.connect_controls.pack_forget()
        soc.leave_button.pack(fill='x', padx=12, pady=(6, 12))
    else:
        soc.connect_controls.pack(fill='x', padx=12, before=soc.participants_caption)
        soc.leave_button.pack_forget()
    def state(control, value):
        if str(control.cget('state')) != value:
            control.configure(state=value)
    for control in (soc.create_button, soc.join_button):
        state(control, 'disabled' if soc.busy else 'normal')
    if soc.client.code and room and not locked:
        soc.invite_card.pack(fill='x', padx=12, pady=6, before=soc.participants_caption)
        code = soc.client.code
        soc.invite_label.configure(text=code[:4] + '-' + code[4:])
        seconds = max(0, int(room.get('invitation_expires', time.time()+600) - time.time()))
        soc.invite_expiry.configure(text=f'Valid for {seconds // 60}:{seconds % 60:02d}' if seconds else 'Invitation expired')
        soc.copy_button.configure(state='normal' if seconds else 'disabled')
    else:
        soc.invite_card.pack_forget()
    if host and not locked:
        soc.start_button.pack(fill='x', padx=12, pady=10, before=soc.leave_button)
        state(soc.start_button, 'normal' if len(members) >= 2 and not soc.busy else 'disabled')
    else:
        soc.start_button.pack_forget()
    peers = {m['user_id'] for m in members if m['user_id'] != own_id}
    compared = bool(peers and peers <= soc.verified_peers)
    if locked and compared and cipher and not cipher.verified:
        soc.confirm_button.pack(fill='x', padx=12, pady=4, before=soc.leave_button)
        state(soc.confirm_button, 'disabled' if soc.busy else 'normal')
    else:
        soc.confirm_button.pack_forget()
    signature = (repr(members), repr((room or {}).get('confirmed', [])), locked, tuple(sorted(soc.verified_peers)))
    if signature != soc._participants_signature:
        for child in soc.participants_frame.winfo_children():
            child.destroy()
        for member in members:
            row = ctk.CTkFrame(soc.participants_frame, fg_color=CONTROL, corner_radius=7)
            row.pack(fill='x', pady=4)
            name = member['username'] + (' · you' if member['user_id'] == own_id else '')
            label(row, name, 13, True, anchor='w').pack(fill='x', padx=10, pady=(7, 0))
            role = ', '.join(member.get('groups', [])) or 'Team member'
            checked = member['user_id'] in (room or {}).get('confirmed', [])
            detail = 'Ready' if checked else ('Verify keys' if locked else 'Connected')
            label(row, f'{role} · {detail}', 11, text_color=MUTED, anchor='w', wraplength=220).pack(fill='x', padx=10, pady=(0, 7))
            if locked and member['user_id'] != own_id:
                verified = member['user_id'] in soc.verified_peers or (cipher and cipher.verified)
                control = button(row, 'Verified' if verified else 'Compare keys', lambda uid=member['user_id']: soc.compare_peer(uid), width=210)
                control.pack(fill='x', padx=10, pady=(0, 8))
                control.configure(state='disabled' if verified else 'normal')
        soc._participants_signature = signature
    soc.participants_caption.configure(text=f'Participants · {len(members)}/16' if room else 'Your team')
    if ready:
        heading, hint = '3  Secure chat is ready', 'Everyone verified. Messages and pings are encrypted between devices.'
    elif locked:
        heading = '2  Verify your teammates'
        hint = 'Waiting for others to verify.' if cipher and cipher.verified else 'Choose Compare keys beside each teammate and type the code they read to you.'
    elif room:
        heading, hint = '1  Bring your team together', 'Share the invite, then start once everyone has joined.' if host else 'You have joined. Your host will start the secure chat.'
    else:
        heading, hint = 'Connect with your team', 'Create a session or paste a teammate’s invitation. People from different groups can use a Team session.'
    soc.stage_label.configure(text=heading)
    soc.safety_label.configure(text=hint)
    permissions = set((room or {}).get('permissions', soc.client.user['permissions']))
    tools = [(p, title) for p, title in [('chat', 'Chat'), ('ping', 'Pings'), ('contact.share', 'Contacts'), ('evidence.share', 'Evidence')] if p in permissions]
    soc.tools_label.configure(text=('Shared tools: ' + ' · '.join(title for _, title in tools)) if room else '')
    for control, permission in ((soc.send_button, 'chat'), (soc.contact_button, 'contact.share'), (soc.evidence_button, 'evidence.share')):
        state(control, 'normal' if ready and permission in permissions and not soc.busy else 'disabled')
    state(soc.message, 'normal' if ready else 'disabled')
    if 'evidence.share' in soc.client.user['permissions']:
        soc.evidence_button.pack(side='left')
    else:
        soc.evidence_button.pack_forget()
    chat_signature = tuple(soc.history)
    if chat_signature != soc._chat_signature:
        bottom = soc.chat.yview()[1] >= .98
        position = soc.chat.yview()[0]
        soc.chat.configure(state='normal')
        soc.chat.delete('1.0', 'end')
        soc.chat.insert('1.0', '\n\n'.join(soc.history))
        soc.chat.configure(state='disabled')
        soc.chat.see('end') if bottom else soc.chat.yview_moveto(position)
        soc._chat_signature = chat_signature
