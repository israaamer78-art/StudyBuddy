(function () {
  const DB_NAME = "studybuddy-local";
  const DB_VERSION = 1;
  const STORE = "snapshots";
  const PROJECT_KEY = "latest-project";

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE)) {
          req.result.createObjectStore(STORE, { keyPath: "id" });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function saveProjectSnapshot(project) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put({
        id: PROJECT_KEY,
        saved_at: new Date().toISOString(),
        project,
      });
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    });
  }

  async function getProjectSnapshot() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const req = tx.objectStore(STORE).get(PROJECT_KEY);
      req.onsuccess = () => {
        db.close();
        resolve(req.result?.project || null);
      };
      req.onerror = () => { db.close(); reject(req.error); };
    });
  }

  async function clearProjectSnapshot() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).delete(PROJECT_KEY);
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    });
  }

  function makeProjectSnapshot(library, settings = {}) {
    return {
      app: "studybuddy",
      format_version: 1,
      exported_at: new Date().toISOString(),
      settings,
      library,
    };
  }

  window.StudyBuddyLocalProjectStore = {
    DB_NAME,
    openDB,
    saveProjectSnapshot,
    getProjectSnapshot,
    clearProjectSnapshot,
    makeProjectSnapshot,
  };
}());
