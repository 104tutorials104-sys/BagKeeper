/* In-app camera for evidence photos.
   Any <input type="file" data-camera data-stamp="BK-XXXX label"> gets a "Take photo" button that opens
   the phone camera inside the page. The picture is captured straight into the form (resized, and
   stamped with the order code, label and date/time) - it is never saved to the phone's gallery.
   If the camera isn't available the normal file input is shown as a fallback. */
(function () {
  var MAX_SIDE = 1600, QUALITY = 0.85;
  var canCamera = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && window.isSecureContext;

  document.querySelectorAll("input[type=file][data-camera]").forEach(init);

  function init(input) {
    var form = input.closest("form");
    var needed = input.required;
    var wrap = document.createElement("div");
    wrap.className = "cam";
    wrap.innerHTML =
      '<img class="cam-thumb" alt="" hidden>' +
      '<button type="button" class="btn ghost cam-btn" style="margin-top:0">Take photo</button>' +
      '<p class="muted cam-msg" style="margin:6px 0 0"></p>' +
      '<button type="button" class="link cam-alt" style="margin-top:6px">Can\'t use the camera? Choose a file instead</button>';
    input.parentNode.insertBefore(wrap, input);
    var thumb = wrap.querySelector(".cam-thumb"), btn = wrap.querySelector(".cam-btn");
    var msg = wrap.querySelector(".cam-msg"), alt = wrap.querySelector(".cam-alt");

    function say(t, tone) { msg.textContent = t; msg.style.color = tone ? "var(--" + tone + ")" : ""; }
    function showFile(f) {
      if (!f) { thumb.hidden = true; return; }
      thumb.src = URL.createObjectURL(f); thumb.hidden = false;
      btn.textContent = "Retake photo";
    }

    if (!canCamera) {                       // plain file input, as before
      wrap.querySelector(".cam-btn").hidden = true; alt.hidden = true;
      say("Take a photo or choose one.");
      return;
    }
    // hide the raw input (the camera fills it); keep `required` working through the submit check
    input.hidden = true; input.required = false;
    say(needed ? "A photo is required." : "Optional.");
    alt.addEventListener("click", function () { input.hidden = !input.hidden; });
    input.addEventListener("change", function () { showFile(input.files[0]); say("Photo ready."); });
    btn.addEventListener("click", function () {
      openCamera(input.dataset.stamp || "", function (file) {
        var dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
        showFile(file); say("Photo ready (" + Math.round(file.size / 1024) + " KB).", "ok");
      }, function (why) { say(why, "bad"); input.hidden = false; });
    });
    if (form && needed) {
      form.addEventListener("submit", function (e) {
        if (!input.files.length) { e.preventDefault(); say("Please take the photo first.", "bad"); btn.focus(); }
      });
    }
  }

  function openCamera(stamp, done, fail) {
    var ov = document.createElement("div");
    ov.className = "cam-ov";
    ov.innerHTML =
      '<video playsinline muted autoplay></video><canvas hidden></canvas>' +
      '<div class="cam-bar">' +
      '<button type="button" class="btn ghost" data-cancel>Cancel</button>' +
      '<button type="button" class="cam-shot" data-shot aria-label="Take photo"></button>' +
      '<button type="button" class="btn" data-use hidden>Use photo</button>' +
      '<button type="button" class="btn ghost" data-retake hidden>Retake</button></div>';
    document.body.appendChild(ov);
    document.body.style.overflow = "hidden";
    var video = ov.querySelector("video"), canvas = ov.querySelector("canvas");
    var shot = ov.querySelector("[data-shot]"), use = ov.querySelector("[data-use]");
    var retake = ov.querySelector("[data-retake]"), cancel = ov.querySelector("[data-cancel]");
    var stream = null, blob = null;

    function close() {
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      ov.remove(); document.body.style.overflow = "";
    }
    cancel.onclick = close;

    navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false
    }).then(function (s) { stream = s; video.srcObject = s; return video.play(); })
      .catch(function (e) {
        close();
        fail(e && e.name === "NotAllowedError"
          ? "Camera is blocked. Allow it for this site in your browser settings, or choose a file."
          : "Couldn't open the camera. Choose a file instead.");
      });

    shot.onclick = function () {
      var w = video.videoWidth, h = video.videoHeight;
      if (!w || !h) return;
      var k = Math.min(1, MAX_SIDE / Math.max(w, h));
      canvas.width = Math.round(w * k); canvas.height = Math.round(h * k);
      var g = canvas.getContext("2d");
      g.drawImage(video, 0, 0, canvas.width, canvas.height);
      // evidence stamp: order code + label + local date/time, along the bottom
      var d = new Date(), pad = function (n) { return (n < 10 ? "0" : "") + n; };
      var text = (stamp ? stamp + "  " : "") + d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
                 " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
      var fs = Math.max(16, Math.round(canvas.width / 38));
      g.fillStyle = "rgba(0,0,0,.55)"; g.fillRect(0, canvas.height - fs * 1.9, canvas.width, fs * 1.9);
      g.fillStyle = "#fff"; g.font = "600 " + fs + "px system-ui, sans-serif"; g.textBaseline = "middle";
      g.fillText(text, fs * 0.6, canvas.height - fs * 0.95);
      canvas.toBlob(function (b) {
        blob = b;
        video.pause(); video.hidden = true; canvas.hidden = false;
        shot.hidden = true; cancel.hidden = true; use.hidden = false; retake.hidden = false;
      }, "image/jpeg", QUALITY);
    };
    retake.onclick = function () {
      blob = null; canvas.hidden = true; video.hidden = false; video.play();
      shot.hidden = false; cancel.hidden = false; use.hidden = true; retake.hidden = true;
    };
    use.onclick = function () {
      if (!blob) return;
      var f = new File([blob], "photo-" + Date.now() + ".jpg", { type: "image/jpeg" });
      close(); done(f);
    };
  }
})();
