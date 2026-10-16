<script>
  import { onMount } from "svelte";
  import { permissionDetails, groupDescriptions } from "./admin-permissions.js";

  let user = $state(null);
  let snapshot = $state.raw(null);
  let csrf = "";
  let busy = $state(true);
  let ready = $state(false);
  let error = $state("");
  let notice = $state("");
  let username = $state("");
  let password = $state("");
  let tab = $state("users");
  let query = $state("");
  let filter = $state("all");
  let selected = $state(null);
  let accountName = $state("");
  let accountPassword = $state("");
  let accountGroups = $state([]);
  let editingAccount = $state(false);
  let groupName = $state("");
  let groupPermissions = $state([]);
  let editingGroup = $state(false);
  let existingGroup = $state(false);
  let pending = $state(null);
  let confirmation;
  const namePattern = "[a-zA-Z0-9]([a-zA-Z0-9_.]|-){2,39}";

  function attachConfirmation(node) {
    confirmation = node;
    return () => { confirmation = undefined; };
  }

  let users = $derived(snapshot?.users ?? []);
  let groups = $derived(snapshot?.groups ?? []);
  let visibleUsers = $derived(users.filter((entry) => entry.username.includes(query.toLowerCase()) && (filter === "all" || entry.status === filter)));
  let pendingCount = $derived(users.filter((entry) => entry.status === "pending").length);
  let selectedPermissions = $derived([...new Set(groups.filter((group) => accountGroups.includes(group.name)).flatMap((group) => group.permissions))].sort());
  let affectedCount = $derived(users.filter((entry) => entry.groups.includes(groupName)).length);

  function clearPrivateState() {
    user = null; snapshot = null; csrf = ""; selected = null;
    editingAccount = false; editingGroup = false; pending = null;
    accountPassword = ""; password = "";
    confirmation?.close();
  }

  async function api(path, method = "GET", body) {
    const response = await fetch(`/admin/api/${path}`, {
      method, credentials: "same-origin", redirect: "error",
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(method !== "GET" ? { "X-CSRF-Token": csrf } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const value = await response.json();
    if (response.status === 401) clearPrivateState();
    if (!response.ok) throw new Error(value.error ?? `Request failed (${response.status})`);
    return value;
  }

  async function refresh() {
    snapshot = await api("state");
  }

  async function run(action) {
    if (busy) return;
    busy = true; error = ""; notice = "";
    try { await action(); }
    catch (failure) { error = failure.message; }
    finally { busy = false; }
  }

  onMount(() => {
    (async () => {
      try {
        const session = await api("session");
        csrf = session.csrf; user = session.user;
        await refresh();
      } catch (failure) {
        clearPrivateState();
        if (!failure.message.includes("Sign in") && !failure.message.includes("expired")) error = failure.message;
      } finally { ready = true; busy = false; }
    })();
  });

  async function signIn(event) {
    event.preventDefault();
    await run(async () => {
      const secret = password; password = "";
      const session = await api("login", "POST", { username, password: secret });
      csrf = session.csrf; user = session.user;
      await refresh();
    });
  }

  function editAccount(entry = null) {
    selected = entry;
    accountName = entry?.username ?? "";
    accountGroups = [...(entry?.groups ?? [])];
    accountPassword = ""; editingAccount = true;
  }

  function editGroup(entry = null) {
    groupName = entry?.name ?? "";
    groupPermissions = [...(entry?.permissions ?? [])];
    existingGroup = !!entry; editingGroup = true;
  }

  function ask(title, description, action) {
    pending = { title, description, action };
    confirmation.showModal();
  }

  function saveAccount(event) {
    event.preventDefault();
    const entry = selected;
    const payload = { groups: [...accountGroups], disabled: !!entry?.disabled };
    if (accountPassword) payload.password = accountPassword;
    if (!entry) payload.username = accountName;
    const granting = groups.filter((group) => payload.groups.includes(group.name)).flatMap((group) => group.permissions);
    ask(entry ? `Save changes to ${entry.username}?` : `Create ${accountName}?`,
      `Groups: ${payload.groups.join(", ") || "none (waiting for approval)"}. ${new Set(granting).size} effective tools. ${entry ? "All existing sign-ins will be revoked and their rooms closed." : "Administrator status is never granted here."}${payload.password ? " A new password will be set." : ""}`,
      async () => {
        await api(entry ? `users/${entry.id}` : "users", entry ? "PUT" : "POST", payload);
        editingAccount = false; accountPassword = "";
        await refresh(); notice = "Account saved.";
      });
  }

  function setBanned(entry, disabled) {
    ask(`${disabled ? "Ban" : "Reinstate"} ${entry.username}?`,
      disabled ? "Access will be blocked immediately. All sign-ins are revoked and their rooms closed." : `Groups retained: ${entry.groups.join(", ") || "none; this account will wait for approval"}. Existing sign-ins remain revoked.`,
      async () => {
        await api(`users/${entry.id}`, "PUT", { groups: [...entry.groups], disabled });
        editingAccount = false; accountPassword = ""; await refresh();
        notice = disabled ? "Account banned and sessions revoked." : "Account reinstated.";
      });
  }

  function saveGroup(event) {
    event.preventDefault();
    const name = groupName;
    const permissions = [...groupPermissions];
    ask(`Save ${name}?`, `This group will grant ${permissions.length} tools. ${affectedCount} member accounts are affected. Their rooms will close; permissions are checked again on every request.`,
      async () => {
        await api(`groups/${encodeURIComponent(name)}`, "PUT", { permissions });
        editingGroup = false; await refresh(); notice = "Group saved.";
      });
  }

  async function confirmAction() {
    const action = pending?.action;
    confirmation.close(); pending = null;
    if (action) await run(action);
    accountPassword = "";
  }

  function cancelAction() {
    confirmation.close(); pending = null; accountPassword = "";
  }
</script>

<main class="admin-shell">
  <header class="admin-header">
    <div><div class="eyebrow">ARGUS MARA / PRIVATE SOC</div><h1>Administration</h1><p>Manage team access, registrations and permissions.</p></div>
    {#if user}
      <div class="admin-actions"><span class="admin-badge">Administrator · {user.username}</span>
        <button disabled={busy} onclick={() => run(refresh)}>Refresh</button>
        <button disabled={busy} onclick={() => run(async () => { await api("logout", "POST", {}); clearPrivateState(); notice = "Signed out."; })}>Sign out</button>
      </div>
    {:else}<span class="admin-badge">Administrator access only</span>{/if}
  </header>

  {#if error}<div class="admin-notice admin-error" role="alert">{error}</div>{/if}
  {#if notice}<div class="admin-notice" role="status">{notice}</div>{/if}
  {#if !ready}<p class="admin-notice" role="status">Checking your session…</p>
  {:else if !user}
    <section class="admin-panel admin-login" aria-labelledby="login-title">
      <h2 id="login-title">Sign in to administration</h2>
      <p>Use an existing SOC administrator account.</p>
      <form onsubmit={signIn}>
        <label>Username<input bind:value={username} autocomplete="username" minlength="3" maxlength="40" required disabled={busy}></label>
        <label>Password<input type="password" bind:value={password} autocomplete="current-password" maxlength="128" required disabled={busy}></label>
        <button class="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p class="admin-muted">Sessions expire after 15 minutes without requests and after one hour at most. The browser does not save your password.</p>
    </section>
  {:else if snapshot}
    <div class="admin-stats">
      <div class="admin-stat"><strong>{pendingCount}</strong>Awaiting approval</div>
      <div class="admin-stat"><strong>{users.filter((entry) => entry.status === "active").length}</strong>Active accounts</div>
      <div class="admin-stat"><strong>{users.filter((entry) => entry.status === "banned").length}</strong>Banned accounts</div>
      <div class="admin-stat"><strong>{groups.length}</strong>Permission groups</div>
    </div>
    <nav aria-label="Administration sections">
      <button aria-current={tab === "users" ? "page" : undefined} onclick={() => { tab = "users"; }}>Users & registrations{pendingCount ? ` (${pendingCount})` : ""}</button>
      <button aria-current={tab === "groups" ? "page" : undefined} onclick={() => { tab = "groups"; }}>Groups & permissions</button>
      <button aria-current={tab === "audit" ? "page" : undefined} onclick={() => { tab = "audit"; }}>Audit log</button>
    </nav>

    {#if tab === "users"}
      <div class="admin-grid">
        <section class="admin-panel" aria-labelledby="users-title">
          <div class="admin-heading"><h2 id="users-title">Team accounts</h2><button class="primary" disabled={busy} onclick={() => editAccount()}>Create account</button></div>
          <div class="admin-toolbar">
            <label>Search username<input type="search" bind:value={query} placeholder="Find an account"></label>
            <label>Status<select bind:value={filter}><option value="all">All accounts</option><option value="pending">Pending approval</option><option value="active">Active</option><option value="banned">Banned</option></select></label>
          </div>
          <div class="admin-scroll"><table>
            <thead><tr><th>Account</th><th>Status</th><th>Groups</th><th>Sign-ins</th><th>Manage</th></tr></thead>
            <tbody>{#each visibleUsers as entry (entry.id)}<tr>
              <td><strong>{entry.username}</strong>{#if entry.admin}<div class="admin-muted">Protected administrator</div>{/if}</td>
              <td><span class={`admin-badge ${entry.status}`}>{entry.status}</span></td>
              <td>{entry.groups.join(", ") || "No access"}</td><td>{entry.active_sessions}</td>
              <td><button disabled={busy || !!entry.admin} aria-label={`Manage ${entry.username}`} onclick={() => editAccount(entry)}>{entry.status === "pending" ? "Review" : "Manage"}</button></td>
            </tr>{:else}<tr><td colspan="5">No accounts match this filter.</td></tr>{/each}</tbody>
          </table></div>
          <p class="admin-muted">Pending accounts cannot sign in. Bans retain memberships for review. Account changes revoke every sign-in and close affected rooms.</p>
        </section>
        <section class="admin-panel" aria-labelledby="account-title">
          {#if editingAccount}
            <h2 id="account-title">{selected ? `Manage ${selected.username}` : "Create account"}</h2>
            <form onsubmit={saveAccount}>
              {#if !selected}<label>New username<input bind:value={accountName} autocomplete="off" pattern={namePattern} title="3–40 letters, digits, dots, hyphens or underscores" minlength="3" maxlength="40" required disabled={busy}></label>{/if}
              <label>{selected ? "New password (optional)" : "Initial password"}<input type="password" bind:value={accountPassword} autocomplete="new-password" minlength="14" maxlength="128" required={!selected} disabled={busy}></label>
              <p class="admin-muted">Use 14–128 characters. Share credentials through a private channel.</p>
              <fieldset disabled={busy}><legend>Group memberships</legend>
                {#each groups as group (group.name)}<label class="check"><input type="checkbox" bind:group={accountGroups} value={group.name}><span><strong>{group.name}</strong><small>{group.permissions.map((permission) => permissionDetails[permission]?.[0] ?? permission).join(", ") || "No tools allowed"}</small></span></label>{/each}
              </fieldset>
              <p><strong>Effective tools:</strong> {selectedPermissions.map((permission) => permissionDetails[permission]?.[0] ?? permission).join(", ") || "None"}.</p>
              <div class="admin-actions"><button class="primary" disabled={busy || (!!selected && selected.status === "pending" && !accountGroups.length)}>{selected?.status === "pending" ? "Approve registration" : "Save account"}</button><button type="button" disabled={busy} onclick={() => { editingAccount = false; accountPassword = ""; }}>Cancel</button></div>
            </form>
            {#if selected}
              <div class="admin-actions">
                <button class="danger" disabled={busy} onclick={() => setBanned(selected, !selected.disabled)}>{selected.disabled ? "Reinstate account" : selected.status === "pending" ? "Reject registration" : "Ban account"}</button>
                <button disabled={busy} onclick={() => { const entry = selected; ask(`Revoke sign-ins for ${entry.username}?`, "Every sign-in is revoked and their rooms close. The account may sign in again if active.", async () => { await api(`users/${entry.id}/revoke`, "POST", {}); await refresh(); notice = "All sign-ins revoked."; }); }}>Revoke all sign-ins</button>
              </div>
            {/if}
          {:else}<h2 id="account-title">Review access</h2><p>Select an account to approve its registration, update groups, reset its password or ban access. New accounts receive no access until a group is assigned.</p><div class="admin-notice">Group permissions add together. Administrator status is separate and can only be bootstrapped on the server.</div>{/if}
        </section>
      </div>
    {:else if tab === "groups"}
      <section class="admin-panel">
        <div class="admin-heading"><h2>Groups & permissions</h2><button class="primary" disabled={busy} onclick={() => editGroup()}>Create group</button></div>
        <p>Memberships combine all granted tools. These tools do not grant administrator access. The matrix shows current permissions; preset descriptions below show the original defaults.</p>
        <div class="admin-scroll"><table class="admin-matrix"><caption>Current permission matrix</caption>
          <thead><tr><th>Tool / permission</th>{#each groups as group (group.name)}<th>{group.name}<br><button disabled={busy} aria-label={`Edit group ${group.name}`} onclick={() => editGroup(group)}>Edit</button></th>{/each}</tr></thead>
          <tbody>{#each snapshot.available_permissions as permission (permission)}<tr><td><strong>{permissionDetails[permission]?.[0] ?? permission}</strong><div class="admin-muted">{permission}<br>{permissionDetails[permission]?.[1]}</div></td>{#each groups as group (group.name)}<td>{group.permissions.includes(permission) ? "Allowed" : "—"}</td>{/each}</tr>{/each}</tbody>
        </table></div>
        <div class="admin-group-summary">{#each groups as group (group.name)}<div><h3>{group.name}</h3><p>{groupDescriptions[group.name] ?? "Custom permissions defined by your administrator."}</p></div>{/each}</div>
        <div class="admin-notice"><strong>Administrator:</strong> approve registrations, manage accounts and groups, reset passwords, revoke sign-ins and read administrative audit records. Protected accounts cannot be edited here. Tool permissions cannot prevent someone pasting sensitive information into an allowed chat; installed public/offline files remain readable on that device.</div>
      </section>
      {#if editingGroup}<section class="admin-panel admin-matrix" aria-labelledby="group-title"><h2 id="group-title">{existingGroup ? `Edit ${groupName}` : "Create group"}</h2>
        <form onsubmit={saveGroup}>
          <label>Group name<input bind:value={groupName} readonly={existingGroup} required minlength="3" maxlength="40" pattern={namePattern} title="3–40 letters, digits, dots, hyphens or underscores" disabled={busy}></label>
          <fieldset disabled={busy}><legend>Allowed tools</legend>{#each snapshot.available_permissions as permission (permission)}<label class="check"><input type="checkbox" bind:group={groupPermissions} value={permission}><span><strong>{permissionDetails[permission]?.[0] ?? permission}</strong><small>{permissionDetails[permission]?.[1]}</small></span></label>{/each}</fieldset>
          <p>{affectedCount} member accounts. Changes close their rooms immediately.</p>
          <div class="admin-actions"><button class="primary" disabled={busy}>Save group</button><button type="button" disabled={busy} onclick={() => { editingGroup = false; }}>Cancel</button>
            {#if existingGroup && !snapshot.protected_groups.includes(groupName)}<button type="button" class="danger" disabled={busy} onclick={() => { const name = groupName; ask(`Delete ${name}?`, `${affectedCount} member accounts will lose this membership. Accounts with no other groups return to pending approval. Affected rooms close.`, async () => { await api(`groups/${encodeURIComponent(name)}`, "DELETE"); editingGroup = false; await refresh(); notice = "Group deleted."; }); }}>Delete group</button>{/if}
          </div>
        </form>
      </section>{/if}
    {:else}
      <section class="admin-panel"><h2>Audit log</h2><p>Latest 100 administrative and registration records, newest first. Times are UTC. Passwords, tokens and message contents are excluded.</p>
        <div class="admin-scroll"><table><thead><tr><th>Time (UTC)</th><th>Actor</th><th>Action</th><th>Target</th></tr></thead><tbody>{#each snapshot.audit as entry (entry.id)}<tr><td>{new Date(entry.at * 1000).toISOString().replace("T", " ").replace(".000Z", "Z")}</td><td>{entry.actor}</td><td>{entry.action}</td><td>{entry.target}</td></tr>{:else}<tr><td colspan="4">No audit records yet.</td></tr>{/each}</tbody></table></div>
      </section>
    {/if}
    <footer><p>Private SOC administration · HTTPS required outside explicit localhost development · 15-minute idle / 1-hour maximum browser session</p><p class="admin-muted">Local tool visibility supports the workflow; the server enforces private API rights. Responses remain simulated and require human approval.</p></footer>
  {/if}
  <dialog {@attach attachConfirmation} oncancel={cancelAction} aria-labelledby="confirm-title" aria-describedby="confirm-description">
    <h2 id="confirm-title">{pending?.title ?? "Confirm change"}</h2><p id="confirm-description">{pending?.description}</p>
    <div class="admin-actions"><button onclick={cancelAction}>Cancel</button><button class="primary" onclick={confirmAction}>Confirm change</button></div>
  </dialog>
</main>
