"""
Enhanced logging configuration for PowerPoint ALT text generator.
Provides file logging with rotation, structured output, and log data export.
"""

import logging
import logging.handlers
import os
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class EnhancedLoggingConfig:
    """Enhanced logging configuration with file rotation and structured output."""
    
    def __init__(self, log_dir: str = "logs", max_bytes: int = 5*1024*1024, backup_count: int = 5):
        """
        Initialize enhanced logging configuration.
        
        Args:
            log_dir: Directory for log files
            max_bytes: Maximum size per log file (default 5MB)
            backup_count: Number of backup files to keep (default 5)
        """
        self.log_dir = Path(log_dir)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.session_id = datetime.now().strftime("run-%Y%m%d-%H%M%S")
        self.session_data = {
            'session_id': self.session_id,
            'start_time': datetime.now().isoformat(),
            'alt_texts_generated': {},
            'failed_generations': [],
            'processing_stats': {}
        }
        
        # Ensure log directory exists
        self.log_dir.mkdir(exist_ok=True)
        
    def setup_logging(self, console_level: str = "INFO", file_level: str = "DEBUG") -> logging.Logger:
        """
        Set up enhanced logging with both console and rotating file handlers.
        
        Args:
            console_level: Log level for console output
            file_level: Log level for file output
            
        Returns:
            Configured root logger
        """
        # Clear any existing handlers
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Set root logger level to the most permissive
        root_logger.setLevel(logging.DEBUG)
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
        )
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, console_level.upper()))
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        # Main rotating file handler
        main_log_file = self.log_dir / f"{self.session_id}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            main_log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, file_level.upper()))
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)
        
        # Error-only file handler
        error_log_file = self.log_dir / f"{self.session_id}-errors.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=self.max_bytes // 2,  # Smaller for errors only
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(error_handler)
        
        # Log initial setup message
        logger = logging.getLogger(__name__)
        logger.info(f"Enhanced logging initialized - Session: {self.session_id}")
        logger.info(f"Log directory: {self.log_dir.absolute()}")
        logger.info(f"Main log: {main_log_file}")
        logger.info(f"Error log: {error_log_file}")
        
        return root_logger
    
    def log_alt_text_generated(self, image_key: str, alt_text: str, metadata: Dict[str, Any]):
        """Log successful ALT text generation."""
        self.session_data['alt_texts_generated'][image_key] = {
            'alt_text': alt_text,
            'metadata': metadata,
            'timestamp': datetime.now().isoformat()
        }
    
    def log_alt_text_failed(self, image_key: str, error: str, metadata: Dict[str, Any]):
        """Log failed ALT text generation."""
        self.session_data['failed_generations'].append({
            'image_key': image_key,
            'error': error,
            'metadata': metadata,
            'timestamp': datetime.now().isoformat()
        })
    
    def update_processing_stats(self, stats: Dict[str, Any]):
        """Update processing statistics."""
        self.session_data['processing_stats'].update(stats)
    
    def export_session_data(self):
        """Export session data to JSON files."""
        try:
            # ALT text mapping export
            alt_map_file = self.log_dir / f"{self.session_id}-alt_map.json"
            with open(alt_map_file, 'w', encoding='utf-8') as f:
                alt_map = {k: v['alt_text'] for k, v in self.session_data['alt_texts_generated'].items()}
                json.dump(alt_map, f, indent=2, ensure_ascii=False)
            
            # Failed generations export
            failed_file = self.log_dir / f"{self.session_id}-failed.json"
            with open(failed_file, 'w', encoding='utf-8') as f:
                json.dump(self.session_data['failed_generations'], f, indent=2, ensure_ascii=False)
            
            # Complete session data export
            session_file = self.log_dir / f"{self.session_id}-session.json"
            session_data_complete = self.session_data.copy()
            session_data_complete['end_time'] = datetime.now().isoformat()
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session_data_complete, f, indent=2, ensure_ascii=False)
            
            logger = logging.getLogger(__name__)
            logger.info(f"Session data exported to {self.log_dir}:")
            logger.info(f"  - ALT text mapping: {alt_map_file}")
            logger.info(f"  - Failed generations: {failed_file}")
            logger.info(f"  - Complete session data: {session_file}")
            
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to export session data: {e}")
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get a summary of the current session."""
        return {
            'session_id': self.session_id,
            'total_alt_texts': len(self.session_data['alt_texts_generated']),
            'total_failures': len(self.session_data['failed_generations']),
            'success_rate': (
                len(self.session_data['alt_texts_generated']) / 
                (len(self.session_data['alt_texts_generated']) + len(self.session_data['failed_generations']))
                if (len(self.session_data['alt_texts_generated']) + len(self.session_data['failed_generations'])) > 0
                else 0
            ) * 100,
            'processing_stats': self.session_data.get('processing_stats', {})
        }


def setup_enhanced_logging(log_dir: str = "logs", console_level: str = "INFO", file_level: str = "DEBUG") -> EnhancedLoggingConfig:
    """
    Convenience function to set up enhanced logging.
    
    Args:
        log_dir: Directory for log files
        console_level: Console log level
        file_level: File log level
        
    Returns:
        EnhancedLoggingConfig instance
    """
    config = EnhancedLoggingConfig(log_dir)
    config.setup_logging(console_level, file_level)
    return config


# Example usage in processor
def integrate_with_processor(processor_instance, log_config: EnhancedLoggingConfig):
    """
    Integrate enhanced logging with the processor.
    
    Args:
        processor_instance: The PPTXAccessibilityProcessor instance
        log_config: The EnhancedLoggingConfig instance
    """
    # Store original methods
    original_generate_alt = processor_instance._generate_alt_text_for_image_with_validation
    
    def enhanced_generate_alt(image_info, debug=False):
        """Enhanced wrapper for ALT text generation with logging."""
        result = original_generate_alt(image_info, debug)
        alt_text, failure_reason = result
        
        # Safely get image key - handle both PPTXImageInfo and temporary objects
        image_key = getattr(image_info, 'image_key', None)
        if not image_key:
            # Fallback key generation for temporary objects
            slide_idx = getattr(image_info, 'slide_idx', 0)
            shape_idx = getattr(image_info, 'shape_idx', 0) 
            filename = getattr(image_info, 'filename', 'unknown')
            image_key = f"slide_{slide_idx}_shape_{shape_idx}_{filename}"
        
        if alt_text:
            log_config.log_alt_text_generated(
                image_key,
                alt_text,
                {
                    'filename': getattr(image_info, 'filename', 'unknown'),
                    'slide_idx': getattr(image_info, 'slide_idx', 0),
                    'dimensions': f"{getattr(image_info, 'width_px', 0)}x{getattr(image_info, 'height_px', 0)}",
                    'is_rendered': getattr(image_info, 'is_rendered', False)
                }
            )
        else:
            log_config.log_alt_text_failed(
                image_key,
                failure_reason or "Unknown failure",
                {
                    'filename': getattr(image_info, 'filename', 'unknown'),
                    'slide_idx': getattr(image_info, 'slide_idx', 0),
                    'dimensions': f"{getattr(image_info, 'width_px', 0)}x{getattr(image_info, 'height_px', 0)}",
                    'is_rendered': getattr(image_info, 'is_rendered', False)
                }
            )
        
        return result
    
    # Replace the method
    processor_instance._generate_alt_text_for_image_with_validation = enhanced_generate_alt