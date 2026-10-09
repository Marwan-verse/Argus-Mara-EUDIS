<script>
  let note = $state(""),
    caveats = $state(false),
    status = $state("");
  function review(event) {
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) return;
    if (!note.trim()) {
      status = "Enter a review note.";
      return;
    }
    status = `Local review recorded at ${new Date().toISOString()}: ${note.trim()}. No operational action was authorized.`;
  }
</script>

<form data-review onsubmit={review}>
  <label
    >Review note <textarea
      name="note"
      maxlength="500"
      required
      bind:value={note}></textarea></label
  >
  <label class="check"
    ><input type="checkbox" name="caveats" required bind:checked={caveats} /> I have
    reviewed the sources and limitations.</label
  >
  <button type="submit">Record local review</button>
  <p role="status" data-review-status>{status}</p>
</form>
