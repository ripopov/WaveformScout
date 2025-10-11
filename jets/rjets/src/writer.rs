use serde::Serialize;
use std::fs::File;
use std::io::{BufWriter, Write};
use anyhow::{Result, Context};
use brotli::enc::BrotliEncoderParams;
use brotli::CompressorWriter;

pub struct TraceWriter {
    writer: Box<dyn Write>,
    record_count: usize,
    annotation_count: usize,
    event_count: usize,
}

impl TraceWriter {
    /// Creates a new TraceWriter for the specified file path.
    ///
    /// Automatically enables Brotli compression if the file path ends with `.br`
    /// (e.g., `trace.jets.br` or `trace.jsonl.br`).
    ///
    /// # Compression
    ///
    /// Brotli compression uses quality level 6 (balanced speed/ratio).
    /// Typical compression ratios: 60-70% size reduction for JSON traces.
    ///
    /// # Examples
    ///
    /// ```no_run
    /// # use rjets::TraceWriter;
    /// # fn main() -> anyhow::Result<()> {
    /// // Uncompressed trace
    /// let mut writer = TraceWriter::new("trace.jets")?;
    ///
    /// // Compressed trace
    /// let mut writer = TraceWriter::new("trace.jets.br")?;
    /// # Ok(())
    /// # }
    /// ```
    pub fn new(file_path: &str) -> Result<Self> {
        let file = File::create(file_path)
            .with_context(|| format!("Failed to create file: {}", file_path))?;

        let writer: Box<dyn Write> = if file_path.ends_with(".br") {
            // Brotli compression enabled
            let buf_writer = BufWriter::new(file);
            let params = BrotliEncoderParams {
                quality: 6,  // Balanced compression
                lgwin: 22,   // Window size
                ..Default::default()
            };
            Box::new(CompressorWriter::with_params(buf_writer, 4096, &params))
        } else {
            // No compression
            Box::new(BufWriter::new(file))
        };

        Ok(TraceWriter {
            writer,
            record_count: 0,
            annotation_count: 0,
            event_count: 0,
        })
    }

    pub fn write_header(&mut self, version: &str, metadata: serde_json::Value) -> Result<()> {
        let header = serde_json::json!({
            "type": "header",
            "version": version,
            "metadata": metadata
        });

        self.write_line(&header)?;
        Ok(())
    }

    pub fn write_record(
        &mut self,
        id: u64,
        parent_id: Option<u64>,
        record_type: &str,
        clk: i64,
        name: &str,
        description: &str,
        data: Option<serde_json::Value>,
    ) -> Result<()> {
        let mut map = serde_json::Map::new();
        map.insert("clk".to_string(), serde_json::Value::Number(clk.into()));
        map.insert("type".to_string(), serde_json::Value::String("record".to_string()));
        map.insert("name".to_string(), serde_json::Value::String(name.to_string()));
        map.insert("record_type".to_string(), serde_json::Value::String(record_type.to_string()));
        map.insert("id".to_string(), serde_json::Value::Number(id.into()));
        map.insert("parent_id".to_string(),
            parent_id.map(|p| serde_json::Value::Number(p.into()))
                .unwrap_or(serde_json::Value::Null));
        map.insert("description".to_string(), serde_json::Value::String(description.to_string()));

        if let Some(d) = data {
            map.insert("data".to_string(), d);
        }

        self.write_line(&serde_json::Value::Object(map))?;
        self.record_count += 1;
        Ok(())
    }

    pub fn write_record_end(&mut self, id: u64, clk: i64) -> Result<()> {
        let mut map = serde_json::Map::new();
        map.insert("clk".to_string(), serde_json::Value::Number(clk.into()));
        map.insert("type".to_string(), serde_json::Value::String("record_end".to_string()));
        map.insert("record_id".to_string(), serde_json::Value::Number(id.into()));

        self.write_line(&serde_json::Value::Object(map))?;
        Ok(())
    }

    pub fn write_annotation(
        &mut self,
        record_id: u64,
        name: &str,
        description: &str,
        data: serde_json::Value,
    ) -> Result<()> {
        let mut map = serde_json::Map::new();
        map.insert("type".to_string(), serde_json::Value::String("annotation".to_string()));
        map.insert("name".to_string(), serde_json::Value::String(name.to_string()));
        map.insert("record_id".to_string(), serde_json::Value::Number(record_id.into()));
        map.insert("description".to_string(), serde_json::Value::String(description.to_string()));
        map.insert("data".to_string(), data);

        self.write_line(&serde_json::Value::Object(map))?;
        self.annotation_count += 1;
        Ok(())
    }

    pub fn write_event(
        &mut self,
        record_id: u64,
        name: &str,
        description: &str,
        clk: i64,
        data: Option<serde_json::Value>,
    ) -> Result<()> {
        let mut map = serde_json::Map::new();
        map.insert("clk".to_string(), serde_json::Value::Number(clk.into()));
        map.insert("type".to_string(), serde_json::Value::String("event".to_string()));
        map.insert("name".to_string(), serde_json::Value::String(name.to_string()));
        map.insert("record_id".to_string(), serde_json::Value::Number(record_id.into()));
        map.insert("description".to_string(), serde_json::Value::String(description.to_string()));

        if let Some(d) = data {
            map.insert("data".to_string(), d);
        }

        self.write_line(&serde_json::Value::Object(map))?;
        self.event_count += 1;
        Ok(())
    }

    pub fn write_footer(&mut self, capture_end_clk: Option<i64>) -> Result<()> {
        let footer = serde_json::json!({
            "type": "footer",
            "capture_end_clk": capture_end_clk,
            "total_records": self.record_count,
            "total_annotations": self.annotation_count,
            "total_events": self.event_count
        });

        self.write_line(&footer)?;
        Ok(())
    }

    fn write_line<T: Serialize>(&mut self, value: &T) -> Result<()> {
        let json = serde_json::to_string(value)
            .context("Failed to serialize to JSON")?;

        writeln!(self.writer, "{}", json)
            .context("Failed to write line")?;

        self.writer.flush()
            .context("Failed to flush writer")?;

        Ok(())
    }
}

impl Drop for TraceWriter {
    fn drop(&mut self) {
        let _ = self.writer.flush();
    }
}
