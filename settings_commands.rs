/// Get mobile settings (MOB2.8).
    #[tauri::command]
    fn mobile_settings_get(app: AppHandle) -> Result<String, String> {
        let cfg = load_config(&app)?.unwrap_or_default();
        Ok(serde_json::json!({
            "llm_backend": cfg.get("llm_backend").and_then(Value::as_str).unwrap_or("ollama"),
            "llm_model": cfg.get("llm_model").and_then(Value::as_str).unwrap_or("llama3.1:8b"),
            "llm_api_key": cfg.get("llm_api_key").and_then(Value::as_str).unwrap_or(""),
            "llm_url": cfg.get("llm_url").and_then(Value::as_str).unwrap_or(""),
            "auto_preview": cfg.get("auto_preview").and_then(Value::as_bool).unwrap_or(true),
            "trash_days": cfg.get("trash_days").and_then(Value::as_str).unwrap_or("30"),
            "last_synced": cfg.get("last_synced").and_then(Value::as_str),
            "outbox_count": 0,
        }).to_string())
    }

    /// Set mobile settings (MOB2.8).
    #[tauri::command]
    fn mobile_settings_set(app: AppHandle, settings: String) -> Result<String, String> {
        let new_settings: Value = serde_json::from_str(&settings).map_err(|e| e.to_string())?;
        let mut cfg = load_config(&app)?.unwrap_or_else(|| serde_json::json!({}));
        
        if let Some(v) = new_settings.get("llm_backend") { cfg["llm_backend"] = v.clone(); }
        if let Some(v) = new_settings.get("llm_model") { cfg["llm_model"] = v.clone(); }
        if let Some(v) = new_settings.get("llm_api_key") { cfg["llm_api_key"] = v.clone(); }
        if let Some(v) = new_settings.get("llm_url") { cfg["llm_url"] = v.clone(); }
        if let Some(v) = new_settings.get("auto_preview") { cfg["auto_preview"] = v.clone(); }
        if let Some(v) = new_settings.get("trash_days") { cfg["trash_days"] = v.clone(); }
        
        save_config(&app, &cfg)?;
        Ok("ok".to_string())
    }

    /// Generate pairing code (MOB2.10).
    #[tauri::command]
    fn mobile_pairing_code(app: AppHandle) -> Result<String, String> {
        let cfg = load_config(&app)?.ok_or("not configured")?;
        let relay_url = cfg.get("relay_url").and_then(Value::as_str).unwrap_or("");
        let secret = cfg.get("secret").and_then(Value::as_str).unwrap_or("");
        
        let code = serde_json::json!({
            "v": 1,
            "relay_url": relay_url,
            "secret": secret,
        });
        let code_b64 = base64::engine::general_purpose::STANDARD.encode(code.to_string());
        Ok(serde_json::json!({ "code": code_b64 }).to_string())
    }

    /// Clear blob cache (MOB2.8).
    #[tauri::command]
    fn mobile_clear_blob_cache(app: AppHandle) -> Result<String, String> {
        let dir = app.path().app_data_dir().map_err(|e| e.to_string())?.join("blobs");
        if dir.exists() {
            std::fs::remove_dir_all(&dir).map_err(|e| e.to_string())?;
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        }
        Ok("ok".to_string())
    }

    /// Get settings for sync (MOB2.9 - desktop calls this).
    #[tauri::command]
    fn mobile_settings_sync(app: AppHandle) -> Result<String, String> {
        let cfg = load_config(&app)?.unwrap_or_default();
        Ok(serde_json::json!({
            "llm_backend": cfg.get("llm_backend").and_then(Value::as_str).unwrap_or("ollama"),
            "llm_model": cfg.get("llm_model").and_then(Value::as_str).unwrap_or("llama3.1:8b"),
            "llm_url": cfg.get("llm_url").and_then(Value::as_str).unwrap_or(""),
            "auto_preview": cfg.get("auto_preview").and_then(Value::as_bool).unwrap_or(true),
            "trash_days": cfg.get("trash_days").and_then(Value::as_str).unwrap_or("30"),
        }).to_string())
    }

    /// Apply synced settings (MOB2.9).
    #[tauri::command]
    fn mobile_settings_apply(app: AppHandle, settings: String) -> Result<String, String> {
        let new_settings: Value = serde_json::from_str(&settings).map_err(|e| e.to_string())?;
        let mut cfg = load_config(&app)?.unwrap_or_else(|| serde_json::json!({}));
        
        if let Some(v) = new_settings.get("llm_backend") { cfg["llm_backend"] = v.clone(); }
        if let Some(v) = new_settings.get("llm_model") { cfg["llm_model"] = v.clone(); }
        if let Some(v) = new_settings.get("llm_url") { cfg["llm_url"] = v.clone(); }
        if let Some(v) = new_settings.get("auto_preview") { cfg["auto_preview"] = v.clone(); }
        if let Some(v) = new_settings.get("trash_days") { cfg["trash_days"] = v.clone(); }
        
        save_config(&app, &cfg)?;
        Ok("ok".to_string())
    }

    /// Push pending outbox items (MOB.7).