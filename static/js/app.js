$(document).ready(function(){
    //connect to the socket server.
    var socket = io.connect('http://' + document.domain + ':' + location.port);

    //receive details from server
    socket.on('tempHeartbeat', function(msg) {
        console.log("Received temp" + msg.temp);
        $('#curr_temp').html(msg.temp);
    });

    socket.on('statusHeartbeat', function(msg) {
        console.log("Got status heartbeat" + msg);
        if (msg.enabled === true){
            $("#enabled").prop('checked', true);
        } else {
            $("#enabled").prop('checked', false);
        }
        if (msg.desired_mode === 0) {
            $('input[name="mode_group"]:checked').val(0);
        } else if (msg.desired_mode === 1) {
            $('input[name="mode_group"]:checked').val(1);
        } else if (msg.desired_mode === 2) {
            $('input[name="mode_group"]:checked').val(2);
        } else {
            $('input[name="mode_group"]:checked').val(3);
        }

        if (msg.current_state === 0) {
            $('#current_status').html("System Off");
        } else if (msg.current_state === 1) {
            $('#current_status').html("Heating to " + msg.desired_temperature);
        } else if (msg.current_state === 2) {
            $('#current_status').html("Cooling to " + msg.desired_temperature);
        } else {
            $('#current_status').html("Fan only mode");
        }

    });

    socket.on('test', function() {
        console.log("test");
    });

    socket.on('connected', function(msg){
        console.log("Connected")
        if (msg.enabled === true){
            $("#enabled").prop('checked', true);
        } else {
            $("#enabled").prop('checked', false);
        }
    });

    $('#enabled').change(function() {
        if(this.checked) {
            socket.emit('enable_system', {data: 'disabled'});
        } else {
            socket.emit('disable_system', {data: 'enabled'});
        }
    });

    $('#desired-temp').change( function() {
        console.log(this.value);
        socket.emit('set_temperature', this.value);
    });
});
