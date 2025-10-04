use serde::Serialize;
use std::fs::File;
use std::io::{BufWriter, Write};
use anyhow::{Result, Context};

pub struct TraceWriter {
    writer: BufWriter<File>,
    record_count: usize,
    annotation_count: usize,
    event_count: usize,
}

impl TraceWriter {
    pub fn new(file_path: &str) -> Result<Self> {
        let file = File::create(file_path)
            .with_context(|| format!("Failed to create file: {}", file_path))?;

        Ok(TraceWriter {
            writer: BufWriter::new(file),
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
        id: &str,
        parent_id: Option<&str>,
        record_type: &str,
        clk: i64,
        name: &str,
        data: Option<serde_json::Value>,
    ) -> Result<()> {
        let mut record = serde_json::json!({
            "type": "record",
            "id": id,
            "record_type": record_type,
            "clk": clk,
            "name": name
        });

        if let Some(pid) = parent_id {
            record["parent_id"] = serde_json::Value::String(pid.to_string());
        }

        if let Some(d) = data {
            record["data"] = d;
        }

        self.write_line(&record)?;
        self.record_count += 1;
        Ok(())
    }

    pub fn write_record_end(&mut self, id: &str, clk: i64) -> Result<()> {
        let record_end = serde_json::json!({
            "type": "record_end",
            "id": id,
            "clk": clk
        });

        self.write_line(&record_end)?;
        Ok(())
    }

    pub fn write_annotation(
        &mut self,
        record_id: &str,
        name: &str,
        data: serde_json::Value,
    ) -> Result<()> {
        let annotation = serde_json::json!({
            "type": "annotation",
            "record_id": record_id,
            "name": name,
            "data": data
        });

        self.write_line(&annotation)?;
        self.annotation_count += 1;
        Ok(())
    }

    pub fn write_event(
        &mut self,
        record_id: &str,
        name: &str,
        clk: i64,
        data: Option<serde_json::Value>,
    ) -> Result<()> {
        let mut event = serde_json::json!({
            "type": "event",
            "record_id": record_id,
            "name": name,
            "clk": clk
        });

        if let Some(d) = data {
            event["data"] = d;
        }

        self.write_line(&event)?;
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
