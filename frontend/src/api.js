// Kochido – schlanker API-Client. Fehler werden mit voller Detail-Kette
// (Backend liefert Ursachen-Kette im `detail`) geworfen, damit Debugging leicht fällt.
export async function api(path, opts = {}) {
  let resp;
  try {
    resp = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
  } catch (err) {
    throw new Error(`Netzwerkfehler bei ${path}: ${err.message}`);
  }
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch {
      /* Body war kein JSON – HTTP-Code reicht */
    }
    throw new Error(detail);
  }
  return resp.json();
}

export const getRecipes = (q = "", tag = "", fav = false) => {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (tag) params.set("tag", tag);
  if (fav) params.set("fav", "1");
  const qs = params.toString();
  return api(`/api/recipes${qs ? `?${qs}` : ""}`);
};

export const getRecipe = (id) => api(`/api/recipes/${id}`);
export const createRecipe = (recipe) =>
  api("/api/recipes", { method: "POST", body: JSON.stringify(recipe) });
export const updateRecipe = (id, recipe) =>
  api(`/api/recipes/${id}`, { method: "PUT", body: JSON.stringify(recipe) });
export const deleteRecipe = (id) => api(`/api/recipes/${id}`, { method: "DELETE" });
export const setFavorite = (id, favorite) =>
  api(`/api/recipes/${id}/favorite`, {
    method: "POST",
    body: JSON.stringify({ favorite }),
  });

export const importFromUrl = (url, maxRecipes = 30) =>
  api("/api/import/url", {
    method: "POST",
    body: JSON.stringify({ url, max_recipes: Number(maxRecipes) || 0 }),
  });
export const importFromText = (text, title) =>
  api("/api/import/text", {
    method: "POST",
    body: JSON.stringify({ text, title }),
  });
export const importCookidoo = (payload) =>
  api("/api/import/cookidoo", {
    method: "POST",
    body: JSON.stringify({ payload }),
  });
export const importBatch = (recipes, listName = "", listSource = "") =>
  api("/api/import/batch", {
    method: "POST",
    body: JSON.stringify({ recipes, list_name: listName, list_source: listSource }),
  });

// Einstellungen & Chat-Assistent
export const getSettings = () => api("/api/settings");
export const saveSettings = (openrouterKey, chatModel) =>
  api("/api/settings", {
    method: "POST",
    body: JSON.stringify({ openrouter_key: openrouterKey, chat_model: chatModel }),
  });
export const getChatModels = () => api("/api/chat/models");
export const sendChat = (message, history) =>
  api("/api/chat", { method: "POST", body: JSON.stringify({ message, history }) });

// Listen
export const getLists = () => api("/api/lists");
export const createList = (name, recipeIds = [], source = "") =>
  api("/api/lists", { method: "POST", body: JSON.stringify({ name, recipe_ids: recipeIds, source }) });
export const renameList = (id, name) =>
  api(`/api/lists/${id}`, { method: "PUT", body: JSON.stringify({ name }) });
export const deleteList = (id) => api(`/api/lists/${id}`, { method: "DELETE" });
export const addToList = (id, recipeIds) =>
  api(`/api/lists/${id}/items`, { method: "POST", body: JSON.stringify({ recipe_ids: recipeIds }) });
export const removeFromList = (id, recipeId) =>
  api(`/api/lists/${id}/items/${recipeId}`, { method: "DELETE" });
export const fetchCookidooCollections = (email, password, country, language) =>
  api("/api/import/cookidoo-collections", {
    method: "POST",
    body: JSON.stringify({ email, password, country, language }),
  });

// Wochenplan
export const getPlan = (from, to) => {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const qs = params.toString();
  return api(`/api/plan${qs ? `?${qs}` : ""}`);
};
export const addPlan = (plan_date, recipe_id, servings, slot = "") =>
  api("/api/plan", {
    method: "POST",
    body: JSON.stringify({ plan_date, recipe_id, servings, slot }),
  });
export const deletePlan = (id) => api(`/api/plan/${id}`, { method: "DELETE" });
