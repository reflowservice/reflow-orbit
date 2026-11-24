/* REFLOW ORBIT — strato cloud (sola lettura).
   Login Microsoft (MSAL, registrazione condivisa "REFLOW ONE" con PLANNER e iMAPS)
   e lettura dei dati prodotti dallo script di monitoraggio:
     - ramo `dati` di questo repository (aggiornamento settimanale automatico,
       GitHub Actions): orbit.enc e img/<codice>.enc, cifrati; chiave in
       <BASE>/chiave_dati.txt su SharePoint, letta via Microsoft Graph;
     - ripiego: <BASE>/dati/orbit.json e <BASE>/dati/img/<id>.png su SharePoint. */
(function () {
  'use strict';
  const CLIENT_ID = 'ef16e670-e362-4954-a912-b628afde91a0';
  const TENANT_ID = 'd53a79c7-2449-4eca-be76-4bd4b7482c96';
  const SITE_HOST = 'reflowservice.sharepoint.com';
  const SITE_PATH = '/sites/ReflowArchive';
  const BASE = '3_CONTROL ROOM/8 - FILE DI CONTESTO AI/REFLOW ORBIT';
  const SCOPES = ['User.Read', 'Sites.ReadWrite.All', 'Files.ReadWrite.All'];
  const PAGES_URL = 'https://reflowservice.github.io/reflow-orbit/';

  const redirectUri = location.hostname.endsWith('github.io') ? PAGES_URL : location.origin + location.pathname;
  const pca = new msal.PublicClientApplication({
    auth: { clientId: CLIENT_ID, authority: `https://login.microsoftonline.com/${TENANT_ID}`, redirectUri },
    cache: { cacheLocation: 'localStorage' }
  });

  const O = window.ORBIT = { account: null, ready: null };
  O.login = () => pca.loginRedirect({ scopes: SCOPES, prompt: 'select_account' });
  O.logout = () => pca.logoutRedirect({ account: O.account, postLogoutRedirectUri: redirectUri });

  async function token() {
    try {
      return (await pca.acquireTokenSilent({ scopes: SCOPES, account: O.account })).accessToken;
    } catch (e) {
      if (e instanceof msal.InteractionRequiredAuthError) { await pca.acquireTokenRedirect({ scopes: SCOPES, account: O.account }); }
      throw e;
    }
  }
  async function graph(path, opt = {}) {
    const t = await token();
    const headers = Object.assign({ Authorization: 'Bearer ' + t }, opt.headers || {});
    return fetch('https://graph.microsoft.com/v1.0' + path, Object.assign({}, opt, { headers }));
  }
  let siteId = null;
  async function site() {
    if (siteId) return siteId;
    const r = await graph(`/sites/${SITE_HOST}:${SITE_PATH}?$select=id`);
    if (!r.ok) throw new Error('Sito SharePoint non raggiungibile (' + r.status + ')');
    return siteId = (await r.json()).id;
  }
  const item = rel => `/sites/${siteId}/drive/root:/${encodeURI(BASE + '/' + rel).replace(/#/g, '%23')}:`;

  /* Dati dell'aggiornamento settimanale automatico (GitHub Actions): ramo `dati`
     di questo repository, solo cifrati (AES-256-GCM). La chiave sta in
     <BASE>/chiave_dati.txt su SharePoint: la legge solo chi entra con l'account
     aziendale e ha accesso alla cartella. Formato file: "ORB1" + nonce (12 byte)
     + testo cifrato con tag; dati aggiuntivi autenticati = nome del file. */
  const DATI_URL = 'https://raw.githubusercontent.com/reflowservice/reflow-orbit/dati/';
  let chiave = null;
  async function key() {
    if (chiave) return chiave;
    await site();
    const r = await graph(item('chiave_dati.txt') + '/content', { cache: 'no-store' });
    if (!r.ok) return null;
    const raw = Uint8Array.from(atob((await r.text()).trim()), c => c.charCodeAt(0));
    return chiave = await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['decrypt']);
  }
  async function cifrato(nome, versione) {
    const k = await key();
    if (!k) throw new Error('chiave dei dati non disponibile');
    const r = await fetch(DATI_URL + nome + '?v=' + encodeURIComponent(versione), { cache: 'no-store' });
    if (!r.ok) throw new Error(`${nome}: ${r.status}`);
    const b = new Uint8Array(await r.arrayBuffer());
    if (String.fromCharCode(...b.subarray(0, 4)) !== 'ORB1') throw new Error(`${nome}: formato non riconosciuto`);
    return crypto.subtle.decrypt({ name: 'AES-GCM', iv: b.subarray(4, 16), additionalData: new TextEncoder().encode(nome) }, k, b.subarray(16));
  }
  O.fonte = null;     // 'automatico' (ramo dati) o 'sharepoint' (dati/orbit.json, aggiornamento manuale)
  O.versione = '';

  async function daSharePoint(rel) {
    await site();
    const r = await graph(item(rel) + '/content', { cache: 'no-store' });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`Lettura di ${rel} non riuscita (${r.status})`);
    return r.json();
  }
  O.getJSON = async rel => {
    if (rel === 'dati/orbit.json') {
      try {
        const d = JSON.parse(new TextDecoder().decode(await cifrato('orbit.enc', Date.now())));
        O.fonte = 'automatico';
        O.versione = d.aggiornato || '';
        return d;
      } catch (e) {
        // Ripiego: ultima copia su SharePoint (calcolo manuale), se i dati automatici non si leggono.
        console.warn('ORBIT: dati automatici non letti, uso SharePoint', e);
        O.fonte = 'sharepoint';
        return daSharePoint(rel);
      }
    }
    return daSharePoint(rel);
  };
  const IMG = {};
  O.imgURL = rel => IMG[rel] = IMG[rel] || (async () => {
    if (rel.endsWith('.enc')) {
      try {
        const nome = rel.replace(/^dati\//, '');
        return URL.createObjectURL(new Blob([await cifrato(nome, O.versione)], { type: 'image/png' }));
      } catch (e) { console.warn('ORBIT: immagine non letta', e); return null; }
    }
    await site();
    const r = await graph(item(rel) + '/content');
    if (!r.ok) return null;
    return URL.createObjectURL(await r.blob());
  })();

  O.ready = (async () => {
    await pca.initialize();
    const r = await pca.handleRedirectPromise();
    O.account = (r && r.account) || pca.getAllAccounts()[0] || null;
    return !!O.account;
  })();
})();
