/* autoconnect.js — 自动重连模块 (v3)
   浏览器会记住授权过的 BLE 设备。页面一打开就自动:
     1. 启动中继 (SSE + 轮询)
     2. 找到上次授权过的设备并直接连上 (免弹窗)
   不用再点「启动中继」「选择设备」。

   复用主脚本的全局变量: bleDevice / writeChar / notifyChar / lastFrame
   复用主脚本的函数:   startRelay / startKeepAlive / stopKeepAlive /
                       stopWave / stopProbe / sendBLE / updatePresetButtons
   本文件必须加载在主脚本之后。
*/
(function () {
  var SERVICE_UUIDS = [
    "0000ee01-0000-1000-8000-00805f9b34fb",
    "0000eee0-0000-1000-8000-00805f9b34fb",
    "0000fef0-0000-1000-8000-00805f9b34fb",
    "0000fff0-0000-1000-8000-00805f9b34fb",
    "0000ffe0-0000-1000-8000-00805f9b34fb",
    "0000fde0-0000-1000-8000-00805f9b34fb",
    "0000aa00-0000-1000-8000-00805f9b34fb"
  ];
  var NOTIFY_PREFIX = "0000ee02";

  var $ = function (id) { return document.getElementById(id); };
  var log = function (msg) {
    var b = $("log-box");
    if (b) b.textContent = "[" + new Date().toLocaleTimeString() + "] " + msg + "\n" + b.textContent;
  };
  var hex = function (b) {
    return Array.prototype.slice.call(b).map(function (x) { return x.toString(16).padStart(2, "0"); }).join(" ");
  };
  var seqByte = function () {
    var el = $("seq-mode");
    return (el && el.value === "random") ? (Math.floor(Math.random() * 256) & 0xFF) : 0x01;
  };

  function knownDevices() {
    try {
      if (!navigator.bluetooth || !navigator.bluetooth.getDevices) return Promise.resolve([]);
      return navigator.bluetooth.getDevices();
    } catch (e) { return Promise.resolve([]); }
  }

  /* ---------- 接管「连接 BLE」按钮 ---------- */
  function takeOverButton() {
    var old = $("btn-connect");
    if (!old || old.dataset.autopatched) return;
    var fresh = old.cloneNode(false);
    old.parentNode.replaceChild(fresh, old);
    fresh.dataset.autopatched = "1";
    fresh.addEventListener("click", function () {
      autoConnect().then(function (ok) {
        if (!ok) log("⚠️ 没有已授权设备, 请在弹窗里选择一次 (之后会自动记住)");
      });
    });
  }

  /* ---------- 核心: 连上已授权设备 ---------- */
  function link(dev) {
    var svcInput = $("service-uuid") ? $("service-uuid").value.trim() : "";
    var wuuid = $("write-uuid") ? $("write-uuid").value.trim() : "";
    var user = svcInput ? svcInput.split(/[,\s;]+/).map(function (s) { return s.trim(); }).filter(Boolean) : [];
    var all = [];
    user.concat(SERVICE_UUIDS).forEach(function (s) { if (all.indexOf(s) < 0) all.push(s); });

    bleDevice = dev;
    return bleDevice.gatt.connect().then(function (server) {
      bleDevice.addEventListener("gattserverdisconnected", function () {
        log("🔌 BLE 被断开");
        $("ble-status").innerHTML = '<span class="pill stopped">未连接</span>';
        $("btn-disconnect").disabled = true;
        $("btn-connect").disabled = false;
        writeChar = null; lastFrame = null;
        stopKeepAlive(); stopWave(); stopProbe();
      });

      var chain = Promise.resolve();
      all.forEach(function (s) {
        chain = chain.then(function () {
          return server.getPrimaryService(s).then(function (svc) {
            return svc.getCharacteristics();
          }).then(function (chars) {
            chars.forEach(function (ch) {
              var p = ch.properties || {};
              if ((p.write || p.writeWithoutResponse) && !writeChar) {
                if (wuuid && ch.uuid.indexOf(wuuid.slice(0, 8)) !== 0) return;
                writeChar = ch;
                log("✅ 写入特征: " + ch.uuid);
              }
              if (p.notify && !notifyChar && ch.uuid.indexOf(NOTIFY_PREFIX) === 0) {
                notifyChar = ch;
              }
            });
          }).catch(function () {});
        });
      });

      return chain.then(function () {
        if (!writeChar) throw new Error("没找到可写 characteristic");

        if (notifyChar) {
          notifyChar.addEventListener("characteristicvaluechanged", function (ev) {
            var v = new Uint8Array(ev.target.value.buffer || ev.target.value);
            log("📨 通知: " + hex(v));
          });
          return notifyChar.startNotifications()
            .then(function () { log("🔔 已订阅通知"); })
            .catch(function (e) { log("⚠️ 通知订阅失败: " + e.message); });
        }
      }).then(function () {
        var im = $("init-mode");
        if (!im || im.value !== "on") return null;
        var init = new Uint8Array([seqByte(), 0x01, 0x00, 0x01, 0x00, 0xC8, 0x11, 0x01]);
        var p = writeChar.properties || {};
        var w = p.write ? writeChar.writeValueWithResponse(init) : writeChar.writeValueWithoutResponse(init);
        return w.then(function () {
          log("🔧 初始化帧已发 [" + hex(init) + "]");
          return new Promise(function (r) { setTimeout(r, 1200); });
        }).catch(function (e) { log("⚠️ 初始化帧失败: " + e.message); });
      }).then(function () {
        $("ble-status").innerHTML = '<span class="pill connected">已连接</span> ' + (bleDevice.name || "");
        log("✅ BLE 已连接");
        $("btn-disconnect").disabled = false;
        $("btn-connect").disabled = true;
        startKeepAlive();
        updatePresetButtons();
      });
    });
  }

  function autoConnect() {
    return knownDevices().then(function (devs) {
      if (!devs || !devs.length) return false;
      var prefix = ($("device-name") ? $("device-name").value.trim() : "SOSEXY") || "SOSEXY";
      var up = prefix.toUpperCase();
      var cand = devs.filter(function (d) { return (d.name || "").toUpperCase().indexOf(up) === 0; });
      if (!cand.length) {
        log("♻️ 有已授权设备 (" + devs.map(function (d) { return d.name; }).join(", ") + ") 但名字不匹配");
        return false;
      }
      log("♻️ 自动重连: " + cand[0].name);
      return link(cand[0]).then(function () { return true; }).catch(function (e) {
        log("⚠️ 自动重连失败: " + (e && e.message ? e.message : e));
        return false;
      });
    });
  }

  /* ---------- 页面加载: 自动启动 + 自动连接 ---------- */
  function boot() {
    takeOverButton();
    try { if (typeof startRelay === "function" && $("btn-start") && !$("btn-start").disabled) startRelay(); }
    catch (e) { log("⚠️ 自动启动中继失败: " + e.message); }

    setTimeout(function () {
      knownDevices().then(function (devs) {
        if (devs && devs.length) {
          log("♻️ 检测到 " + devs.length + " 个已授权设备, 正在自动连接...");
          autoConnect();
        } else {
          log("💡 首次使用: 点「连接 BLE」选一次设备, 之后每次打开本页都会自动连上");
        }
      });
    }, 600);
  }

  if (document.readyState === "complete" || document.readyState === "interactive") {
    setTimeout(boot, 0);
  } else {
    window.addEventListener("DOMContentLoaded", boot);
  }
})();
