/**
 * Timetable Editor JavaScript
 * Handles drag and drop functionality, teacher assignments, and timetable management
 */

// Global variables to store data from template
let allSubjects = {};
let currentBatch = '';
let allDays = [];
let periodsPerDay = 6;

document.addEventListener('DOMContentLoaded', function() {
    // Load data from hidden inputs
    loadTemplateData();
    
    // Initialize components
    initializeDragAndDrop();
    initializeTeacherSelects();
    initializeButtonActions();
    initializeTabNavigation();
    initializeSubjectButtons();
    initializeCellSelection();
    
    // Update the print timetable link with the default batch
    updatePrintTimetableLink();
    
    // Show a welcome toast
    showToast('Welcome to Timetable Editor', 'Drag and drop subjects to create your timetable.', 'info');
});

/**
 * Load data from hidden inputs
 */
function loadTemplateData() {
    try {
        // Get all subjects data
        const allSubjectsInput = document.getElementById('all-subjects-data');
        if (allSubjectsInput) {
            allSubjects = JSON.parse(allSubjectsInput.value);
        }
        
        // Get current batch
        const currentBatchInput = document.getElementById('current-batch-data');
        if (currentBatchInput) {
            currentBatch = currentBatchInput.value;
        }
        
        // Get days
        const allDaysInput = document.getElementById('all-days-data');
        if (allDaysInput) {
            allDays = JSON.parse(allDaysInput.value);
        }
        
        // Get periods per day
        const periodsPerDayInput = document.getElementById('periods-per-day-data');
        if (periodsPerDayInput) {
            periodsPerDay = parseInt(periodsPerDayInput.value);
        }
    } catch (error) {
        console.error('Error loading template data:', error);
    }
}

/**
 * Initialize drag and drop functionality
 */
function initializeDragAndDrop() {
    // Make subject items draggable
    const subjectItems = document.querySelectorAll('.subject-item');
    subjectItems.forEach(item => {
        item.setAttribute('draggable', 'true');
        
        item.addEventListener('dragstart', function(e) {
            e.dataTransfer.setData('text/plain', JSON.stringify({
                subjectId: this.querySelector('button').getAttribute('data-subject-id'),
                subjectName: this.querySelector('button').getAttribute('data-subject-name'),
                subjectCode: this.querySelector('button').getAttribute('data-subject-code')
            }));
            this.classList.add('dragging');
            
            // Add pulse animation to valid drop targets
            document.querySelectorAll('.timetable-cell').forEach(cell => {
                cell.classList.add('pulse');
            });
        });
        
        item.addEventListener('dragend', function() {
            this.classList.remove('dragging');
            
            // Remove pulse animation
            document.querySelectorAll('.timetable-cell').forEach(cell => {
                cell.classList.remove('pulse');
            });
        });
    });
    
    // Make timetable content draggable
    document.querySelectorAll('.timetable-content').forEach(content => {
        content.setAttribute('draggable', 'true');
        
        content.addEventListener('dragstart', function(e) {
            e.stopPropagation();
            const data = {
                subjectId: this.getAttribute('data-subject-id'),
                subjectName: this.getAttribute('data-subject-name'),
                teacherId: this.getAttribute('data-teacher-id'),
                teacherName: this.getAttribute('data-teacher-name'),
                fromCell: true
            };
            e.dataTransfer.setData('text/plain', JSON.stringify(data));
            this.classList.add('dragging');
            
            // Store the source cell for swapping
            window.dragSourceCell = this.closest('.timetable-cell');
        });
        
        content.addEventListener('dragend', function() {
            this.classList.remove('dragging');
            window.dragSourceCell = null;
        });
    });
    
    // Make timetable cells drop targets
    const timetableCells = document.querySelectorAll('.timetable-cell');
    timetableCells.forEach(cell => {
        cell.addEventListener('dragover', function(e) {
            e.preventDefault();
            this.classList.add('dragover');
        });
        
        cell.addEventListener('dragleave', function() {
            this.classList.remove('dragover');
        });
        
        cell.addEventListener('drop', function(e) {
            e.preventDefault();
            this.classList.remove('dragover');
            
            try {
                const data = JSON.parse(e.dataTransfer.getData('text/plain'));
                const day = this.getAttribute('data-day');
                const period = this.getAttribute('data-period');
                const batchId = document.querySelector('.tab-pane.active').getAttribute('data-batch-id');
                
                // Handle swapping if this is a cell-to-cell drag
                if (data.fromCell && window.dragSourceCell && window.dragSourceCell !== this) {
                    // Get the content from the target cell (if any)
                    const targetContent = this.querySelector('.timetable-content');
                    
                    // Get the content from the source cell
                    const sourceContent = window.dragSourceCell.querySelector('.timetable-content');
                    
                    if (sourceContent) {
                        // Remove from source cell
                        window.dragSourceCell.innerHTML = '';
                        
                        // If target has content, move it to the source cell
                        if (targetContent) {
                            targetContent.remove();
                            window.dragSourceCell.appendChild(targetContent);
                        }
                        
                        // Add source content to target cell
                        this.appendChild(sourceContent);
                    }
                    
                    // Update timetable data
                    updateTimetableData();
                    
                    // Show success toast
                    showToast('Assignment Swapped', 'Timetable assignments have been swapped', 'success');
                    return;
                }
                
                // Check if cell already has content
                if (this.querySelector('.timetable-content')) {
                    if (!confirm('Replace existing assignment?')) {
                        return;
                    }
                    this.innerHTML = '';
                }
                
                // Create assignment content
                const content = document.createElement('div');
                content.className = 'timetable-content';
                content.setAttribute('draggable', 'true');
                content.setAttribute('data-subject-id', data.subjectId);
                content.setAttribute('data-subject-name', data.subjectName);
                
                // If this is from a cell, use the existing teacher data
                if (data.fromCell) {
                    content.setAttribute('data-teacher-id', data.teacherId);
                    content.setAttribute('data-teacher-name', data.teacherName);
                    
                    content.innerHTML = `
                        <button class="remove-btn" title="Remove">&times;</button>
                        <strong>${data.subjectName}</strong>
                        <small class="text-muted">${data.teacherName}</small>
                    `;
                } else {
                    // For new assignments, add a teacher select
                    content.innerHTML = `
                        <strong>${data.subjectName}</strong>
                        <small class="text-muted">${data.subjectCode}</small>
                        <select class="teacher-select form-select form-select-sm mt-2" 
                                data-subject-id="${data.subjectId}" 
                                data-day="${day}" 
                                data-period="${period}">
                            <option value="">Select Teacher</option>
                            ${getTeacherOptionsForSubject(data.subjectId)}
                        </select>
                        <button class="remove-btn" title="Remove">&times;</button>
                    `;
                }
                
                this.appendChild(content);
                
                // Add drag event listeners to the new content
                content.addEventListener('dragstart', function(e) {
                    e.stopPropagation();
                    const cellData = {
                        subjectId: this.getAttribute('data-subject-id'),
                        subjectName: this.getAttribute('data-subject-name'),
                        teacherId: this.getAttribute('data-teacher-id') || '',
                        teacherName: this.getAttribute('data-teacher-name') || '',
                        fromCell: true
                    };
                    e.dataTransfer.setData('text/plain', JSON.stringify(cellData));
                    this.classList.add('dragging');
                    window.dragSourceCell = this.closest('.timetable-cell');
                });
                
                content.addEventListener('dragend', function() {
                    this.classList.remove('dragging');
                    window.dragSourceCell = null;
                });
                
                // Initialize the new teacher select
                const newSelect = content.querySelector('.teacher-select');
                if (newSelect) {
                    newSelect.addEventListener('change', handleTeacherChange);
                }
                
                // Initialize remove button
                const removeBtn = content.querySelector('.remove-btn');
                removeBtn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    if (confirm('Remove this assignment?')) {
                        content.parentNode.innerHTML = '';
                        updateTimetableData();
                    }
                });
                
                // Update timetable data
                updateTimetableData();
                
                // Show success toast
                showToast('Assignment Added', `${data.subjectName} assigned to ${getDayName(day)}, Period ${period}`, 'success');
                
            } catch (error) {
                console.error('Error handling drop:', error);
                showToast('Error', 'Failed to assign subject. Please try again.', 'error');
            }
        });
    });
    
    // Enable removing assignments by clicking on them
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-btn')) {
            e.stopPropagation();
            const content = e.target.closest('.timetable-content');
            if (content && confirm('Remove this assignment?')) {
                content.parentNode.innerHTML = '';
                updateTimetableData();
            }
        }
    });
}

/**
 * Initialize subject buttons
 */
function initializeSubjectButtons() {
    document.querySelectorAll('.subject-item button').forEach(button => {
        button.addEventListener('click', function() {
            const subjectName = this.getAttribute('data-subject-name');
            const subjectId = this.getAttribute('data-subject-id');
            const subjectCode = this.getAttribute('data-subject-code');
            
            // Get the selected teacher
            const teacherSelect = this.closest('.subject-item').querySelector('.teacher-select');
            const teacherId = teacherSelect.value;
            const teacherName = teacherSelect.options[teacherSelect.selectedIndex].text;
            
            addSubject(subjectName, subjectId, subjectCode, teacherId, teacherName);
        });
    });
}

/**
 * Add subject to the currently selected cell
 */
function addSubject(subjectName, subjectId, subjectCode, teacherId, teacherName) {
    const selectedCell = document.querySelector('.timetable-cell.selected');
    if (!selectedCell) {
        showToast('Error', 'Please select a cell in the timetable first', 'error');
        return;
    }
    
    // Check if cell already has content
    if (selectedCell.querySelector('.timetable-content')) {
        if (!confirm('Replace existing assignment?')) {
            return;
        }
        selectedCell.innerHTML = '';
    }
    
    // Create content for the cell
    const contentDiv = document.createElement('div');
    contentDiv.className = 'timetable-content';
    contentDiv.setAttribute('draggable', 'true');
    contentDiv.setAttribute('data-subject-id', subjectId);
    contentDiv.setAttribute('data-subject-name', subjectName);
    contentDiv.setAttribute('data-teacher-id', teacherId);
    contentDiv.setAttribute('data-teacher-name', teacherName);
    
    contentDiv.innerHTML = `
        <button class="remove-btn" title="Remove">&times;</button>
        <strong>${subjectName}</strong>
        <small class="text-muted">${teacherName}</small>
    `;
    
    // Add drag event listeners to the new content
    contentDiv.addEventListener('dragstart', function(e) {
        e.stopPropagation();
        const cellData = {
            subjectId: this.getAttribute('data-subject-id'),
            subjectName: this.getAttribute('data-subject-name'),
            teacherId: this.getAttribute('data-teacher-id'),
            teacherName: this.getAttribute('data-teacher-name'),
            fromCell: true
        };
        e.dataTransfer.setData('text/plain', JSON.stringify(cellData));
        this.classList.add('dragging');
        window.dragSourceCell = this.closest('.timetable-cell');
    });
    
    contentDiv.addEventListener('dragend', function() {
        this.classList.remove('dragging');
        window.dragSourceCell = null;
    });
    
    // Add the new content
    selectedCell.appendChild(contentDiv);
    
    // Initialize remove button
    const removeBtn = contentDiv.querySelector('.remove-btn');
    removeBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (confirm('Remove this assignment?')) {
            contentDiv.parentNode.innerHTML = '';
            updateTimetableData();
        }
    });
    
    // Update timetable data
    updateTimetableData();
    
    // Remove the 'selected' class
    selectedCell.classList.remove('selected');
    
    // Show success toast
    const day = selectedCell.getAttribute('data-day');
    const period = selectedCell.getAttribute('data-period');
    showToast('Assignment Added', `${subjectName} assigned to ${getDayName(day)}, Period ${period}`, 'success');
}

/**
 * Initialize cell selection
 */
function initializeCellSelection() {
    // Add click event listeners to cells for selection
    const cells = document.querySelectorAll('.timetable-cell');
    cells.forEach(cell => {
        cell.addEventListener('click', function(e) {
            // Don't select if clicking on content or buttons
            if (e.target.closest('.timetable-content') || e.target.closest('button')) {
                return;
            }
            
            // Remove selected class from all cells
            cells.forEach(c => c.classList.remove('selected'));
            // Add selected class to clicked cell
            this.classList.add('selected');
        });
    });
}

/**
 * Initialize teacher select dropdowns
 */
function initializeTeacherSelects() {
    document.querySelectorAll('.teacher-select').forEach(select => {
        select.addEventListener('change', handleTeacherChange);
    });
}

/**
 * Handle teacher selection change
 */
function handleTeacherChange() {
    const subjectId = this.getAttribute('data-subject-id');
    const day = this.getAttribute('data-day');
    const period = this.getAttribute('data-period');
    const teacherId = this.value;
    
    // Get the content div and update its attributes
    const contentDiv = this.closest('.timetable-content');
    if (contentDiv) {
        contentDiv.setAttribute('data-teacher-id', teacherId);
        contentDiv.setAttribute('data-teacher-name', this.options[this.selectedIndex].text);
    }
    
    // Update timetable data
    updateTimetableData();
    
    // Show feedback
    if (teacherId) {
        const teacherName = this.options[this.selectedIndex].text;
        showToast('Teacher Assigned', `${teacherName} assigned to this period`, 'info');
    }
}

/**
 * Get teacher options HTML for a specific subject
 */
function getTeacherOptionsForSubject(subjectId) {
    // This would typically fetch from a data attribute or API
    // For now, we'll use a placeholder approach
    const teacherSelect = document.querySelector(`#teacher-data-${subjectId}`);
    return teacherSelect ? teacherSelect.innerHTML : '';
}

/**
 * Update timetable data in hidden form field
 */
function updateTimetableData() {
    const timetableData = {};
    
    // Process all batches
    document.querySelectorAll('.tab-pane').forEach(tab => {
        const batchId = tab.getAttribute('data-batch-id');
        timetableData[batchId] = {};
        
        // Process days and periods
        const days = allDays || ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
        days.forEach(day => {
            timetableData[batchId][day] = [];
            
            // For each period in this day
            for (let period = 0; period < (periodsPerDay || 6); period++) {
                const cell = tab.querySelector(`td[data-day="${day}"][data-period="${period}"]`);
                const content = cell ? cell.querySelector('.timetable-content') : null;
                
                if (content) {
                    timetableData[batchId][day].push({
                        subject_id: content.getAttribute('data-subject-id'),
                        teacher_id: content.getAttribute('data-teacher-id'),
                        subject_name: content.getAttribute('data-subject-name'),
                        teacher_name: content.getAttribute('data-teacher-name')
                    });
                } else {
                    timetableData[batchId][day].push(null); // Empty cell
                }
            }
        });
    });
    
    // Update hidden input with JSON data
    document.getElementById('timetable-data').value = JSON.stringify(timetableData);
}

/**
 * Initialize button actions
 */
function initializeButtonActions() {
    // Save button
    const saveButton = document.getElementById('save-timetable');
    if (saveButton) {
        saveButton.addEventListener('click', function() {
            updateTimetableData();
            showToast('Saving...', 'Saving your timetable changes', 'info');
            
            // Submit the form
            document.getElementById('timetable-form').submit();
        });
    }
    
    // Print button
    const printButton = document.getElementById('print-timetable-link');
    if (printButton) {
        printButton.addEventListener('click', function() {
            updatePrintTimetableLink();
        });
    }
}

/**
 * Function to update the print timetable link with current batch information
 */
function updatePrintTimetableLink() {
    const printLink = document.getElementById('print-timetable-link');
    if (printLink && currentBatch) {
        // Parse the batch string to get individual components
        const batchParts = currentBatch.split(',');
        if (batchParts.length >= 4) {
            const courseId = batchParts[0].trim().replace('{', '').replace('}', '');
            const year = batchParts[1].trim();
            const semester = batchParts[2].trim();
            const batchId = batchParts[3].trim();
            
            // Update the href with query parameters
            const baseUrl = printLink.getAttribute('href').split('?')[0];
            printLink.href = baseUrl + 
                `?course_id=${courseId}&year=${year}&semester=${semester}&batch_id=${batchId}`;
        }
    }
}

/**
 * Initialize tab navigation
 */
function initializeTabNavigation() {
    document.querySelectorAll('.batch-tabs .nav-link').forEach(tab => {
        tab.addEventListener('click', function() {
            // Update active tab
            document.querySelectorAll('.batch-tabs .nav-link').forEach(t => {
                t.classList.remove('active');
            });
            this.classList.add('active');
            
            // Update active tab content
            const targetId = this.getAttribute('data-bs-target').substring(1);
            document.querySelectorAll('.tab-pane').forEach(pane => {
                pane.classList.remove('active', 'show');
            });
            document.getElementById(targetId).classList.add('active', 'show');
            
            // Update current batch
            const tabPane = document.getElementById(targetId);
            if (tabPane) {
                currentBatch = tabPane.getAttribute('data-batch-id');
                
                // Update the batch select dropdown to match
                const batchSelect = document.getElementById('batchSelect');
                for (let i = 0; i < batchSelect.options.length; i++) {
                    if (batchSelect.options[i].value === currentBatch) {
                        batchSelect.selectedIndex = i;
                        break;
                    }
                }
                
                // Update the subjects list
                updateSubjectsList();
                
                // Update the print timetable link
                updatePrintTimetableLink();
            }
        });
    });
    
    // Handle batch select change
    const batchSelect = document.getElementById('batchSelect');
    if (batchSelect) {
        batchSelect.addEventListener('change', function() {
            currentBatch = this.value;
            updateSubjectsList();
            
            // Find and activate the corresponding tab
            const batchIndex = Array.from(document.querySelectorAll('#batchTabs .nav-link'))
                .findIndex(tab => {
                    const tabPane = document.querySelector(tab.getAttribute('data-bs-target'));
                    return tabPane && tabPane.getAttribute('data-batch-id') === currentBatch;
                });
            
            if (batchIndex !== -1) {
                const tabToActivate = document.querySelector(`#batch-${batchIndex + 1}-tab`);
                if (tabToActivate) {
                    bootstrap.Tab.getOrCreateInstance(tabToActivate).show();
                }
            }
            
            // Update the print timetable link
            updatePrintTimetableLink();
        });
    }
}

/**
 * Update the subjects list when batch changes
 */
function updateSubjectsList() {
    const subjectsListElement = document.getElementById('subjectsList');
    if (!subjectsListElement || !allSubjects || !currentBatch || !allSubjects[currentBatch]) {
        return;
    }
    
    // Clear existing content
    subjectsListElement.innerHTML = '';
    
    // Add subjects for selected batch
    const batchSubjects = allSubjects[currentBatch];
    for (const [subjectName, subjectData] of Object.entries(batchSubjects)) {
        const subjectElement = document.createElement('div');
        subjectElement.className = 'subject-item';
        subjectElement.setAttribute('draggable', 'true');
        
        let teacherOptions = '';
        subjectData.teachers.forEach(teacher => {
            teacherOptions += `<option value="${teacher.teacher_id}">${teacher.teacher_name}</option>`;
        });
        
        subjectElement.innerHTML = `
            <div><strong>${subjectName}</strong> <span class="text-muted">(${subjectData.subject_code})</span></div>
            <div class="mt-1">
                <label class="form-label">
                    <i class="bi bi-person-badge me-1"></i>
                    Select Teacher:
                </label>
                <select class="form-select teacher-select">
                    ${teacherOptions}
                </select>
            </div>
            <button class="btn btn-sm btn-primary mt-2"
                    data-subject-name="${subjectName}"
                    data-subject-id="${subjectData.subject_id}"
                    data-subject-code="${subjectData.subject_code}">
                <i class="bi bi-plus-circle me-1"></i>
                Add to Timetable
            </button>
        `;
        
        subjectsListElement.appendChild(subjectElement);
    }
    
    // Reinitialize drag and drop for new subject items
    initializeDragAndDrop();
    
    // Reinitialize subject buttons
    initializeSubjectButtons();
}

/**
 * Show toast notification
 */
function showToast(title, message, type = 'info') {
    // Create toast container if it doesn't exist
    let toastContainer = document.querySelector('.toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(toastContainer);
    }
    
    // Create toast element
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.className = `toast show`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.id = toastId;
    
    // Set toast color based on type
    let bgColor = 'bg-info';
    let icon = 'info-circle';
    
    switch (type) {
        case 'success':
            bgColor = 'bg-success';
            icon = 'check-circle';
            break;
        case 'error':
            bgColor = 'bg-danger';
            icon = 'exclamation-circle';
            break;
        case 'warning':
            bgColor = 'bg-warning';
            icon = 'exclamation-triangle';
            break;
    }
    
    // Set toast content
    toast.innerHTML = `
        <div class="toast-header ${bgColor} text-white">
            <i class="bi bi-${icon} me-2"></i>
            <strong class="me-auto">${title}</strong>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
        <div class="toast-body">
            ${message}
        </div>
    `;
    
    // Add toast to container
    toastContainer.appendChild(toast);
    
    // Initialize close button
    toast.querySelector('.btn-close').addEventListener('click', function() {
        toast.remove();
    });
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

/**
 * Get day name from day number
 */
function getDayName(day) {
    const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
    return days[parseInt(day) - 1] || `Day ${day}`;
}

/**
 * Check for conflicts in the timetable
 * This function checks for teacher conflicts (same teacher assigned to multiple classes at the same time)
 */
function checkTimetableConflicts() {
    const conflicts = [];
    const teacherAssignments = {};
    
    // For each batch tab
    document.querySelectorAll('.tab-pane').forEach(tab => {
        const batchId = tab.getAttribute('data-batch-id');
        const batchName = tab.getAttribute('data-batch-name') || `Batch ${batchId}`;
        
        // For each cell in this batch's timetable
        tab.querySelectorAll('.timetable-cell').forEach(cell => {
            const day = cell.getAttribute('data-day');
            const period = cell.getAttribute('data-period');
            const content = cell.querySelector('.timetable-content');
            
            if (content) {
                const teacherId = content.getAttribute('data-teacher-id');
                if (teacherId) {
                    const teacherName = content.getAttribute('data-teacher-name');
                    const key = `${day}-${period}-${teacherId}`;
                    
                    if (!teacherAssignments[key]) {
                        teacherAssignments[key] = [];
                    }
                    
                    teacherAssignments[key].push({
                        batchId,
                        batchName,
                        day,
                        period,
                        teacherName
                    });
                }
            }
        });
    });
    
    // Check for conflicts (teacher assigned to multiple batches at the same time)
    for (const key in teacherAssignments) {
        if (teacherAssignments[key].length > 1) {
            conflicts.push(teacherAssignments[key]);
        }
    }
    
    return conflicts;
}

/**
 * Display conflicts to the user
 */
function showConflicts() {
    const conflicts = checkTimetableConflicts();
    
    if (conflicts.length === 0) {
        showToast('No Conflicts', 'Your timetable has no teacher assignment conflicts.', 'success');
        return;
    }
    
    // Create modal if it doesn't exist
    let modal = document.getElementById('conflicts-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.id = 'conflicts-modal';
        modal.setAttribute('tabindex', '-1');
        modal.setAttribute('aria-labelledby', 'conflicts-modal-label');
        modal.setAttribute('aria-hidden', 'true');
        
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header bg-danger text-white">
                        <h5 class="modal-title" id="conflicts-modal-label">
                            <i class="bi bi-exclamation-triangle me-2"></i>
                            Timetable Conflicts Detected
                        </h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body" id="conflicts-list">
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
    }
    
    // Populate conflicts
    const conflictsList = document.getElementById('conflicts-list');
    conflictsList.innerHTML = '';
    
    conflicts.forEach((conflict, index) => {
        const conflictDiv = document.createElement('div');
        conflictDiv.className = 'card mb-3 border-danger';
        
        const dayName = getDayName(conflict[0].day);
        
        conflictDiv.innerHTML = `
            <div class="card-header bg-danger bg-opacity-10 text-danger">
                <strong>Conflict #${index + 1}:</strong> ${conflict[0].teacherName} assigned to multiple batches on ${dayName}, Period ${conflict[0].period}
            </div>
            <ul class="list-group list-group-flush">
                ${conflict.map(c => `
                    <li class="list-group-item">
                        <i class="bi bi-arrow-right-circle me-2"></i>
                        Batch: ${c.batchName}
                    </li>
                `).join('')}
            </ul>
        `;
        
        conflictsList.appendChild(conflictDiv);
    });
    
    // Show modal
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}

// Add a global function to check conflicts
window.checkConflicts = showConflicts; 