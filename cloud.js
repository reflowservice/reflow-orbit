/* REFLOW ORBIT — strato cloud (sola lettura).
   Login Microsoft (MSAL, registrazione condivisa "REFLOW ONE" con PLANNER e iMAPS)
   e lettura via Microsoft Graph dei file prodotti dallo script di monitoraggio:
     <BASE>/dati/orbit.json      stato, serie e sfalci di tutti gli impianti
     <BASE>/dati/img/<id>.png    immagine satellitare recente di ogni impianto */
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

  O.getJSON = async rel => {
    await site();
    const r = await graph(item(rel) + '/content', { cache: 'no-store' });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`Lettura di ${rel} non riuscita (${r.status})`);
    return r.json();
  };
  const IMG = {};
  O.imgURL = rel => IMG[rel] = IMG[rel] || (async () => {
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
