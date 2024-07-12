from queue import Queue
from abc import ABC, abstractmethod
from typing import Generator, Any


class SystemCall(ABC):
    """SystemCall yielded by Task to handle with Scheduler"""

    @abstractmethod
    def handle(self, scheduler: 'Scheduler', task: 'Task') -> bool:
        """
        :param scheduler: link to scheduler to manipulate with active tasks
        :param task: task which requested the system call
        :return: an indication that the task must be scheduled again
        """


Coroutine = Generator[SystemCall | None, Any, None]


class Task:
    def __init__(self, task_id: int, target: Coroutine) -> None:
        """
        :param task_id: id of the task
        :param target: coroutine to run. Coroutine can produce system calls.
        System calls are being executed by scheduler and the result sends back to coroutine.
        """
        self.task_id = task_id
        self.target = target
        self.result = None

    def set_syscall_result(self, result: Any) -> None:
        """
        Saves result of the last system call
        """
        self.result = result

    def step(self) -> SystemCall | None:
        """
        Performs one step of coroutine, i.e. sends result of last system call
        to coroutine (generator), gets yielded value and returns it.
        """
        return self.target.send(self.result)


class Scheduler:
    """Scheduler to manipulate with tasks"""

    def __init__(self) -> None:
        self.task_id = 0
        self.task_queue: Queue[Task] = Queue()
        self.task_map: dict[int, Task] = {}  # task_id -> task
        self.wait_map: dict[int, list[Task]] = {}  # task_id -> list of waiting tasks
        self.wait_t = 0

    def _schedule_task(self, task: Task) -> None:
        """
        Add task into task queue
        :param task: task to schedule for execution
        """
        self.task_queue.put(task)
        self.task_map[task.task_id] = task

    def new(self, target: Coroutine) -> int:
        """
        Create and schedule new task
        :param target: coroutine to wrap in task
        :return: id of newly created task
        """
        self.task_id += 1
        self._schedule_task(Task(self.task_id, target))
        return self.task_id

    def exit_task(self, task_id: int) -> bool:
        """
        PRIVATE API: can be used only from scheduler itself or system calls
        Hint: do not forget to reschedule waiting tasks
        :param task_id: task to remove from scheduler
        :return: true if task id is valid
        """
        return task_id in self.task_map

    def wait_task(self, task_id: int, wait_id: int) -> bool:
        """
        PRIVATE API: can be used only from scheduler itself or system calls
        :param task_id: task to hold on until another task is finished
        :param wait_id: id of the other task to wait for
        :return: true if task and wait ids are valid task ids
        """
        self.wait_t = task_id
        return True

    def run(self, ticks: int | None = None) -> None:
        """
        Executes tasks consequently, gets yielded system calls,
        handles them and reschedules task if needed
        :param ticks: number of iterations (task steps), infinite if not passed
        """

        try:
            count_tick = 0
            while not self.task_queue.empty():
                if (ticks is not None) and (ticks == count_tick):
                    break
                count_tick += 1
                if bool(self.wait_map):
                    task = self.wait_map[self.wait_t][0]
                    isn = True
                else:
                    isn = False
                    task = self.task_queue.get()
                if self.exit_task(task.task_id):
                    try:
                        ret = task.step()
                        if ret is not None:
                            ret.handle(self, task)
                    except StopIteration:
                        del self.task_map[task.task_id]
                        if isn:
                            del self.wait_map[self.wait_t]
                        continue
                    if not isn:
                        self.task_queue.put(task)
        except KeyboardInterrupt:
            return

    def empty(self) -> bool:
        """Checks if there are some scheduled tasks"""
        return not bool(self.task_map)


class GetTid(SystemCall):
    """System call to get current task id"""

    def handle(self, scheduler: Scheduler, task: Task) -> bool:
        task.set_syscall_result(task.task_id)
        return False


class NewTask(SystemCall):
    """System call to create new task from target coroutine"""

    def __init__(self, target: Coroutine) -> None:
        self.target = target

    def handle(self, scheduler: Scheduler, task: Task) -> bool:
        id = scheduler.new(self.target)
        task.set_syscall_result(id)
        return False


class KillTask(SystemCall):
    """System call to kill task with particular task id"""

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id

    def handle(self, scheduler: Scheduler, task: Task) -> bool:
        if self.task_id in scheduler.task_map:
            scheduler.task_map[self.task_id].target.close()
            del scheduler.task_map[self.task_id]
        return False


class WaitTask(SystemCall):
    """System call to wait task with particular task id"""

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id

    def handle(self, scheduler: Scheduler, task: Task) -> bool:
        if self.task_id in scheduler.task_map:
            scheduler.wait_map[self.task_id] = [scheduler.task_map[self.task_id]]
            scheduler.wait_task(self.task_id, 0)
        return False
