/// Mobile chat: keyword search + LLM answer (MOB2.7).
    #[tauri::command]
    fn mobile_chat(app: AppHandle, query: String, history: String) -> Result<String, String> {
        let conn = open_lib(&app)?;
        
        // 1. Keyword search over local copy (MOB.6)
        let arts = crate::sync::search_artifacts(&conn, &query).map_err(|e| e.to_string())?;
        if arts.is_empty() {
            return Ok(serde_json::json!({
                "answer": "I couldn't find anything relevant in your notes.",
                "citations": Vec::<String>::new(),
                "error": null
            }).to_string());
        }
        
        // 2. Build passages from matched artifacts (newest first, cap tokens)
        let mut passages = Vec::new();
        let mut total_chars = 0;
        const MAX_CHARS: usize = 8000;
        
        for art in arts {
            let body = art["body"].as_str().unwrap_or("");
            if body.is_empty() { continue; }
            let passage = format!("Source [{}]: {}", art["id"].as_str().unwrap_or(""), body);
            if total_chars + passage.len() > MAX_CHARS { break; }
            total_chars += passage.len();
            passages.push(passage);
        }
        
        if passages.is_empty() {
            return Ok(serde_json::json!({
                "answer": "I couldn't find anything relevant in your notes.",
                "citations": Vec::<String>::new(),
                "error": null
            }).to_string());
        }
        
        // 3. Load config for LLM backend and API key
        let cfg = load_config(&app)?.ok_or("not configured")?;
        let dek = cfg.get("dek").and_then(Value::as_str).and_then(dek_from_hex).ok_or("locked")?;
        let backend = cfg.get("llm_backend").and_then(Value::as_str).unwrap_or("ollama");
        let model = cfg.get("llm_model").and_then(Value::as_str).unwrap_or("llama3.1:8b");
        let custom_url = if backend == "custom" { cfg.get("llm_url").and_then(Value::as_str).unwrap_or("") } else { "" };
        let api_key = cfg.get("llm_api_key").and_then(Value::as_str).unwrap_or("");
        
        // 4. Build prompt
        let context = passages.join("\n\n---\n\n");
        let prompt = format!(
            "Answer the question using ONLY the provided context. Cite sources by their [id] in square brackets.\n\nContext:\n{}\n\nQuestion: {}\n\nAnswer:",
            context, query
        );
        
        // 5. Call LLM - for mobile we need to call provider directly
        let answer = call_llm_mobile(&backend, &model, &custom_url, &api_key, &prompt)
            .map_err(|e| e.to_string())?;
        
        // 6. Extract citations from answer
        let cited_ids = extract_citations(&answer);
        
        Ok(serde_json::json!({
            "answer": answer,
            "citations": cited_ids,
            "error": null
        }).to_string())
    }
    
    fn call_llm_mobile(backend: &str, model: &str, custom_url: &str, api_key: &str, prompt: &str) -> Result<String, String> {
        // Use ureq to call the provider directly
        let body = serde_json::json!({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": false
        });
        
        let (url, auth_header) = match backend {
            "ollama" => {
                let url = if custom_url.is_empty() { "http://127.0.0.1:11434/api/chat" } else { custom_url };
                (url.to_string(), None)
            }
            "openrouter" => ("https://openrouter.ai/api/v1/chat/completions".to_string(), Some(format!("Bearer {}", api_key)))
            "opencode-go" => ("https://opencode.ai/zen/go/v1/chat/completions".to_string(), Some(format!("Bearer {}", api_key)))
            "custom" => (custom_url.to_string(), if api_key.is_empty() { None } else { Some(format!("Bearer {}", api_key)) })
            _ => return Err(format!("unknown backend: {}", backend))
        };
        
        let mut req = ureq::post(&url)
            .set("Content-Type", "application/json");
        if let Some(auth) = auth_header {
            req = req.set("Authorization", &auth);
        }
        
        let resp = req.send_json(body).map_err(|e| format!("HTTP error: {}", e))?;
        
        if !resp.status().is_success() {
            let status = resp.status();
            let err_text = resp.into_string().unwrap_or_default();
            return Err(format!("LLM error {}: {}", status, err_text));
        }
        
        let json: serde_json::Value = resp.into_json().map_err(|e| format!("JSON parse: {}", e))?;
        
        // Extract answer from various response formats
        let answer = json["choices"][0]["message"]["content"]
            .as_str()
            .or_else(|| json["message"]["content"].as_str())
            .or_else(|| json["response"].as_str())
            .unwrap_or("No response from model")
            .to_string();
        
        Ok(answer)
    }
    
    fn extract_citations(text: &str) -> Vec<String> {
        let re = regex::Regex::new(r"\[([a-f0-9-]{36})\]").unwrap();
        re.captures_iter(text)
            .map(|cap| cap[1].to_string())
            .collect()
    }