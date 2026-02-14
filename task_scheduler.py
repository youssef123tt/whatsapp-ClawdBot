"""
Task Scheduler for WhatsApp Messages
Handles scheduled and recurring messages using APScheduler
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import logging
import uuid

logger = logging.getLogger(__name__)

# Module-level callback so APScheduler can serialize jobs without
# pulling in the entire TaskScheduler instance (which contains the scheduler).
_send_callback: Optional[Callable] = None


async def _execute_scheduled_message(phone_number: str, message: str):
    """Module-level job function called by APScheduler."""
    try:
        if not _send_callback:
            logger.error("No send callback configured!")
            return
        logger.info(f"Sending scheduled message to {phone_number}")
        await _send_callback(phone_number=phone_number, message=message)
        logger.info(f"Scheduled message sent to {phone_number}")
    except Exception as e:
        logger.error(f"Error sending scheduled message: {e}")



class TaskScheduler:
    """
    Scheduler for WhatsApp messages
    Supports one-time and recurring messages
    """
    
    def __init__(
        self,
        database_url: str = "sqlite:///scheduler.db",
        timezone: str = "UTC"
    ):
        self.timezone = timezone
        
        # Configure job store
        jobstores = {
            'default': SQLAlchemyJobStore(url=database_url)
        }
        
        # Initialize scheduler
        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            timezone=timezone
        )
        
        # Callback for sending messages
        self.send_message_callback: Optional[Callable] = None
        
    def set_send_callback(self, callback: Callable):
        """
        Set the callback function for sending messages
        
        Args:
            callback: Async function that takes (phone_number, message)
        """
        global _send_callback
        _send_callback = callback
        self.send_message_callback = callback
    
    async def start(self):
        """Start the scheduler"""
        self.scheduler.start()
        logger.info("Task scheduler started")
    
    async def shutdown(self):
        """Shutdown the scheduler"""
        self.scheduler.shutdown()
        logger.info("Task scheduler shutdown")
    
    async def schedule_message(
        self,
        phone_number: str,
        message: str,
        schedule_time: datetime,
        recurring: bool = False,
        recurrence_pattern: Optional[str] = None,
        task_name: Optional[str] = None
    ) -> str:
        """
        Schedule a message to be sent
        
        Args:
            phone_number: Recipient phone number
            message: Message text
            schedule_time: When to send the message
            recurring: Whether this is a recurring message
            recurrence_pattern: Recurrence pattern (daily, weekly, monthly)
            task_name: Optional name for the task
        
        Returns:
            Task ID
        """
        task_id = task_name or f"msg_{uuid.uuid4().hex[:8]}"
        
        # Prepare job kwargs
        job_kwargs = {
            "phone_number": phone_number,
            "message": message
        }
        
        # Determine trigger
        if recurring and recurrence_pattern:
            trigger = self._create_recurring_trigger(
                schedule_time,
                recurrence_pattern
            )
        else:
            trigger = DateTrigger(run_date=schedule_time)
        
        # Add job
        self.scheduler.add_job(
            func=_execute_scheduled_message,
            trigger=trigger,
            id=task_id,
            kwargs=job_kwargs,
            replace_existing=True,
            misfire_grace_time=300  # 5 minutes
        )
        
        logger.info(
            f"Scheduled message to {phone_number} at {schedule_time} "
            f"(recurring: {recurring})"
        )
        
        return task_id
    
    def _create_recurring_trigger(
        self,
        start_time: datetime,
        pattern: str
    ):
        """
        Create a recurring trigger based on pattern
        
        Args:
            start_time: Start time for recurrence
            pattern: Recurrence pattern (daily, weekly, monthly)
        
        Returns:
            APScheduler trigger
        """
        if pattern == "daily":
            return CronTrigger(
                hour=start_time.hour,
                minute=start_time.minute,
                second=start_time.second,
                timezone=self.timezone
            )
        elif pattern == "weekly":
            return CronTrigger(
                day_of_week=start_time.weekday(),
                hour=start_time.hour,
                minute=start_time.minute,
                second=start_time.second,
                timezone=self.timezone
            )
        elif pattern == "monthly":
            return CronTrigger(
                day=start_time.day,
                hour=start_time.hour,
                minute=start_time.minute,
                second=start_time.second,
                timezone=self.timezone
            )
        elif pattern.startswith("every_"):
            # Handle patterns like "every_2_hours", "every_30_minutes"
            parts = pattern.split("_")
            if len(parts) >= 3:
                interval = int(parts[1])
                unit = parts[2]
                
                unit_map = {
                    "hours": "hours",
                    "hour": "hours",
                    "minutes": "minutes",
                    "minute": "minutes",
                    "days": "days",
                    "day": "days"
                }
                
                interval_unit = unit_map.get(unit)
                if interval_unit:
                    return IntervalTrigger(
                        **{interval_unit: interval},
                        start_date=start_time,
                        timezone=self.timezone
                    )
        
        # Default to daily if pattern not recognized
        logger.warning(f"Unknown pattern '{pattern}', defaulting to daily")
        return CronTrigger(
            hour=start_time.hour,
            minute=start_time.minute,
            timezone=self.timezone
        )
    
    async def _send_scheduled_message(
        self,
        phone_number: str,
        message: str
    ):
        """
        Internal method to send scheduled message
        Called by APScheduler
        """
        try:
            if not self.send_message_callback:
                logger.error("No send callback configured!")
                return
            
            logger.info(f"Sending scheduled message to {phone_number}")
            
            await self.send_message_callback(
                phone_number=phone_number,
                message=message
            )
            
            logger.info(f"Scheduled message sent to {phone_number}")
            
        except Exception as e:
            logger.error(f"Error sending scheduled message: {e}")
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a scheduled task
        
        Args:
            task_id: ID of task to cancel
        
        Returns:
            True if cancelled successfully
        """
        try:
            self.scheduler.remove_job(task_id)
            logger.info(f"Cancelled task: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Error cancelling task {task_id}: {e}")
            return False
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a scheduled task
        
        Args:
            task_id: Task ID
        
        Returns:
            Task information or None
        """
        try:
            job = self.scheduler.get_job(task_id)
            if not job:
                return None
            
            return {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
                "kwargs": job.kwargs
            }
        except Exception as e:
            logger.error(f"Error getting task {task_id}: {e}")
            return None
    
    def list_tasks(self) -> list[Dict[str, Any]]:
        """
        List all scheduled tasks
        
        Returns:
            List of task information
        """
        try:
            jobs = self.scheduler.get_jobs()
            
            return [
                {
                    "id": job.id,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                    "phone_number": job.kwargs.get("phone_number"),
                    "message": job.kwargs.get("message")
                }
                for job in jobs
            ]
        except Exception as e:
            logger.error(f"Error listing tasks: {e}")
            return []
    
    def reschedule_task(
        self,
        task_id: str,
        new_schedule_time: datetime
    ) -> bool:
        """
        Reschedule an existing task
        
        Args:
            task_id: Task ID
            new_schedule_time: New schedule time
        
        Returns:
            True if rescheduled successfully
        """
        try:
            self.scheduler.reschedule_job(
                task_id,
                trigger=DateTrigger(run_date=new_schedule_time)
            )
            logger.info(f"Rescheduled task {task_id} to {new_schedule_time}")
            return True
        except Exception as e:
            logger.error(f"Error rescheduling task {task_id}: {e}")
            return False
    
    def pause_task(self, task_id: str) -> bool:
        """Pause a scheduled task"""
        try:
            self.scheduler.pause_job(task_id)
            logger.info(f"Paused task: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Error pausing task {task_id}: {e}")
            return False
    
    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task"""
        try:
            self.scheduler.resume_job(task_id)
            logger.info(f"Resumed task: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Error resuming task {task_id}: {e}")
            return False
