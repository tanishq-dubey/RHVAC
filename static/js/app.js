$(document).ready(function(){
    //connect to the socket server.
    var socket = io.connect('http://' + document.domain + ':' + location.port);

    //receive details from server
    socket.on('tempHeartbeat', function(msg) {
        console.log("Received temp" + msg.temp);
        $('#curr_temp').html(msg.temp);
    });

    socket.on('statusHeartbeat', function(msg) {
        console.log("Got status heartbeat");
        console.log("Enabled: " + msg.enabled);
        if (msg.enabled === true){
            $("#enabled").prop('checked', true);
        } else {
            $("#enabled").prop('checked', false);
        }

        console.log("Mode: " + msg.desired_mode);
        if (msg.desired_mode === 'Mode.COOL') {
            $("input[name=mode_group][value=0]").prop('checked', true);
        } else if (msg.desired_mode === 'Mode.HEAT') {
            $("input[name=mode_group][value=1]").prop('checked', true);
        } else if (msg.desired_mode === 'Mode.AUTO') {
            $("input[name=mode_group][value=2]").prop('checked', true);
        } else {
            $("input[name=mode_group][value=3]").prop('checked', true);
        }

        console.log("State: " + msg.current_state);
        if (msg.current_state === 'State.OFF') {
            $('#current_status').html("System Off");
        } else if (msg.current_state === 'State.HEATING') {
            $('#current_status').html("Heating to " + msg.desired_temperature);
        } else if (msg.current_state === 'State.COOLING') {
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
